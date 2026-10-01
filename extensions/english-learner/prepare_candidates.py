"""Select existing unreviewed learner candidates and expose authoring gaps.

Selection checks identity and simple textual constraints, not semantic quality.
Every retained language-model candidate still needs linguistic review.
"""

import argparse
import json
import re
import sqlite3
import tarfile
from collections import defaultdict
from pathlib import Path

CREATOR = "gpt-oss:120b"
SOURCE = "training/data/generated.tar.xz"
MANUAL_EXAMPLE_SYNSETS = {"omw-en-09849598-n"}


def normalized(text):
    return " ".join(text.split()).casefold()


def short_text(value, limit=500):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def examples(candidate, word, synset_id):
    if synset_id in MANUAL_EXAMPLE_SYNSETS:
        return []
    pattern = re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)", re.IGNORECASE)
    result = []
    seen = set()
    for text in candidate.get("examples", []):
        if not short_text(text) or not pattern.search(text):
            continue
        key = normalized(text)
        if key not in seen:
            result.append(text.strip())
            seen.add(key)
        if len(result) == 2:
            break
    return result


def row_from_sense(pair, sense):
    return {
        "word": sense["lemma"],
        "frequency_rank": pair["frequency_rank"],
        "word_id": sense["entry_id"],
        "sense_id": sense["sense_id"],
        "synset_id": pair["synset_id"],
        "base_definition": pair["definitions"][0],
        "source": "omw-en:1.4",
        "creator": "WordNet",
        "status": "unreviewed",
    }


def candidate_identities(database, by_synset):
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    identities = defaultdict(list)
    for record in connection.execute("""
        SELECT f.form, ss.id AS synset_id, se.id AS sense_id,
               e.id AS word_id, lemma.form AS word
        FROM forms f JOIN senses se ON se.entry_rowid=f.entry_rowid
        JOIN entries e ON e.rowid=se.entry_rowid
        JOIN synsets ss ON ss.rowid=se.synset_rowid
        JOIN forms lemma ON lemma.entry_rowid=e.rowid AND lemma.rank=0
        JOIN lexicons l ON l.rowid=se.lexicon_rowid
        WHERE l.specifier='omw-en:1.4'
    """):
        if record["synset_id"] in by_synset:
            identities[(record["form"], record["synset_id"])].append(dict(record))
    connection.close()
    return identities


def archive_candidates(path, database, by_synset):
    identities = candidate_identities(database, by_synset)
    result = defaultdict(list)
    wanted_words = {word for word, _ in identities}
    with tarfile.open(path, "r:xz") as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith(".json"):
                continue
            word = Path(member.name).stem
            if word not in wanted_words:
                continue
            with archive.extractfile(member) as stream:
                candidates = json.load(stream)
            for candidate in candidates:
                synset_id = candidate["id"]
                if synset_id not in by_synset:
                    continue
                definitions = by_synset[synset_id]["definitions"]
                if not isinstance(candidate.get("source_definition"), str):
                    continue
                if normalized(candidate["source_definition"]) not in {
                    normalized(d) for d in definitions
                }:
                    continue
                for identity in identities.get((word, synset_id), []):
                    result[synset_id].append(
                        {
                            **identity,
                            "source_word": word,
                            "plain_language": candidate.get("alternative_definition"),
                            "examples": examples(candidate, word, synset_id),
                            "source": SOURCE + "#" + member.name,
                        }
                    )
    return result


def native_labels(pair, row):
    # Usage-domain links in this OMW release are not register labels: e.g.
    # figurative language points to cakewalk. Do not promote exemplars to labels.
    domains = []
    domain_evidence = []
    for relation in pair["relations"]:
        if not relation["forms"]:
            continue
        label = relation["forms"][0]
        evidence = {"label": label, "synset_id": relation["target_synset_id"]}
        if relation["type"] == "domain_topic":
            domains.append(label)
            domain_evidence.append(evidence)
    if domains:
        row["domains"] = list(dict.fromkeys(domains))
        row["domain_evidence"] = domain_evidence


def select_examples(pair, candidates, selected, sense_priority):
    synset_id = pair["synset_id"]
    covered = False
    for candidate in candidates:
        sense_id = candidate["sense_id"]
        if sense_id not in sense_priority or not candidate["examples"]:
            continue
        row = selected[sense_id]
        if row.get("examples"):
            continue
        row["examples"] = candidate["examples"]
        row["example_source_word"] = candidate["source_word"]
        row["example_source"] = candidate["source"]
        row["source"] = candidate["source"]
        row["creator"] = CREATOR
        covered = True
    if not covered:
        fallback = next((c for c in candidates if c["examples"]), None)
        if fallback:
            row = selected.setdefault(
                fallback["sense_id"],
                {
                    "word": fallback["word"],
                    "word_id": fallback["word_id"],
                    "sense_id": fallback["sense_id"],
                    "synset_id": synset_id,
                    "frequency_rank": pair["frequency_rank"],
                    "base_definition": pair["definitions"][0],
                    "supporting_synonym": True,
                    "status": "unreviewed",
                },
            )
            row.update(
                {
                    "examples": fallback["examples"],
                    "example_source_word": fallback["source_word"],
                    "example_source": fallback["source"],
                    "source": fallback["source"],
                    "creator": CREATOR,
                }
            )
            covered = True
    return covered


def select(inventory, archive):
    by_synset = {}
    selected = {}
    sense_priority = {}
    for pair in inventory:
        by_synset.setdefault(pair["synset_id"], pair)
        for sense in pair["senses"]:
            sense_priority.setdefault(sense["sense_id"], pair["frequency_rank"])
            row = selected.setdefault(sense["sense_id"], row_from_sense(pair, sense))
            row["forms"] = sense["forms"]
            if sense["tags"]:
                row["native_tags"] = sense["tags"]
            if sense["syntactic_frames"]:
                row["native_syntactic_frames"] = sense["syntactic_frames"]
    missing_examples = []
    missing_plain = []
    native_rows = []
    for synset_id, pair in by_synset.items():
        candidates = sorted(
            archive[synset_id],
            key=lambda c: (
                sense_priority.get(c["sense_id"], 100000),
                c["source_word"] != c["word"],
                c["source_word"],
                c["sense_id"],
            ),
        )
        representative = selected[pair["senses"][0]["sense_id"]]
        native = row_from_sense(pair, pair["senses"][0])
        native_labels(pair, native)
        if "domains" in native or "register" in native:
            native_rows.append(native)
        plain = next(
            (
                c
                for c in candidates
                if short_text(c["plain_language"])
                and normalized(c["plain_language"])
                not in {normalized(d) for d in pair["definitions"]}
            ),
            None,
        )
        if plain:
            # A synset explanation can use any of its validated synonyms.
            representative["plain_language"] = plain["plain_language"].strip()
            representative["plain_language_source"] = plain["source"]
            representative["source"] = plain["source"]
            representative["creator"] = CREATOR
        else:
            missing_plain.append(pair)
        if any(pair["examples"]):
            continue
        covered = select_examples(pair, candidates, selected, sense_priority)
        if not covered:
            missing_examples.append(pair)
    return selected, missing_examples, missing_plain, native_rows


def write_jsonl(path, records):
    with path.open("w") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path.home() / ".wn_data/wn.db")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = [json.loads(line) for line in args.inventory.open()]
    by_synset = {row["synset_id"]: row for row in reversed(inventory)}
    archive = archive_candidates(args.candidates, args.database, by_synset)
    selected, missing_examples, missing_plain, native_rows = select(inventory, archive)
    candidate_rows = sorted(
        (
            row
            for row in selected.values()
            if row.get("plain_language") or row.get("examples")
        ),
        key=lambda r: (r["frequency_rank"], r["synset_id"], r["sense_id"]),
    )
    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output / "candidates.jsonl", candidate_rows)
    write_jsonl(args.output / "native-labels.jsonl", native_rows)
    write_jsonl(args.output / "missing-examples.jsonl", missing_examples)
    write_jsonl(args.output / "missing-plain-language.jsonl", missing_plain)
    summary = {
        "candidate_rows": len(candidate_rows),
        "rows_with_plain_language": sum("plain_language" in r for r in candidate_rows),
        "rows_with_examples": sum(bool(r.get("examples")) for r in candidate_rows),
        "candidate_examples": sum(len(r.get("examples", [])) for r in candidate_rows),
        "rows_with_domains": sum("domains" in r for r in native_rows),
        "rows_with_register": sum("register" in r for r in native_rows),
        "supporting_synonym_rows": sum(
            r.get("supporting_synonym", False) for r in candidate_rows
        ),
        "synsets_missing_examples": len(missing_examples),
        "synsets_missing_plain_language": len(missing_plain),
        "manual_example_synsets": sorted(MANUAL_EXAMPLE_SYNSETS),
        "status": "unreviewed",
    }
    (args.output / "candidate-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
