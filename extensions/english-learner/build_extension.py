"""Build an additive WN-LMF extension from scoped, provenance-bearing records.

No lexical entries, senses, or synsets are created. All referenced identities
must already exist in the base lexicon. Examples are attached to both their
source sense and its existing concept; existing concept examples are preserved.
"""

import argparse
import gzip
import hashlib
import json
import lzma
import sqlite3
from collections import Counter
from pathlib import Path

from wn import lmf
from wn.learner import ANNOTATION_TYPE, validate_learner_fields

BASE = {"id": "omw-en", "version": "1.4"}
FIELDS = ("domains", "register", "usage", "grammar_notes", "usage_tips")


def read_records(path):
    opener = lzma.open if path.suffix == ".xz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{number}: expected an object")
                yield row


def provenance(row):
    for field in ("creator", "source", "status"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ValueError(f"missing provenance: {field}")
    meta = {key: row[key] for key in ("creator", "source", "status")}
    if row.get("reviewer"):
        meta["contributor"] = row["reviewer"]
        meta["note"] = "AI review: " + row.get("review_status", "unspecified")
    return meta


def definition(row, scope="sense"):
    fields = {"schema_version": 1, "scope": scope}
    if scope == "word":
        fields.update(word_id=row["word_id"], irregular_forms=row["irregular_forms"])
    else:
        fields.update({key: row[key] for key in FIELDS if row.get(key)})
        if row.get("irregular_forms"):
            fields["irregular_forms"] = row["irregular_forms"]
    validate_learner_fields(fields)
    meta = provenance(row)
    meta.update(
        type=ANNOTATION_TYPE, description=json.dumps(fields, ensure_ascii=False)
    )
    data = {
        "text": row.get("plain_language") or row["base_definition"],
        "language": "en",
        "meta": meta,
    }
    if scope == "sense":
        data["sourceSense"] = row["sense_id"]
    return data


def entities(row, entries, senses, synsets):
    for key in ("word_id", "sense_id", "synset_id", "base_definition"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError(f"missing identity/reference: {key}")
    entry = entries.setdefault(
        row["word_id"],
        {
            "id": row["word_id"],
            "external": True,
            "senses": [],
        },
    )
    if row["sense_id"] not in senses:
        sense = {"id": row["sense_id"], "external": True, "examples": []}
        senses[row["sense_id"]] = (row["word_id"], row["synset_id"], sense)
        entry["senses"].append(sense)
    word_id, synset_id, sense = senses[row["sense_id"]]
    if (word_id, synset_id) != (row["word_id"], row["synset_id"]):
        raise ValueError(f"conflicting sense identity: {row['sense_id']}")
    synset = synsets.setdefault(
        row["synset_id"],
        {
            "id": row["synset_id"],
            "external": True,
            "definitions": [],
            "examples": [],
        },
    )
    return sense, synset


def annotations(row, seen_irregular):
    result = []
    if row.get("plain_language"):
        plain = {**row, "source": row.get("plain_language_source", row["source"])}
        for field in FIELDS:
            plain.pop(field, None)
        plain.pop("irregular_forms", None)
        result.append(definition(plain, row.get("plain_language_scope", "sense")))
    if any(row.get(key) for key in FIELDS):
        scoped = {key: value for key, value in row.items() if key != "plain_language"}
        scoped.pop("irregular_forms", None)
        result.append(definition(scoped, row.get("scope", "sense")))
    if row.get("irregular_forms"):
        scope = row.get("irregular_forms_scope", "sense")
        identity = row["word_id"] if scope == "word" else row["sense_id"]
        previous = seen_irregular.get(identity)
        if previous is not None and previous != row["irregular_forms"]:
            raise ValueError(f"conflicting irregular forms: {identity}")
        if previous is None:
            irregular = {
                key: value
                for key, value in row.items()
                if key not in (*FIELDS, "plain_language")
            }
            result.append(definition(irregular, scope))
            seen_irregular[identity] = row["irregular_forms"]
    return result


def add_examples(row, sense, synset, seen, counts):
    for text in row.get("examples", []):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("example must be a nonempty string")
        key = (row["sense_id"], text.strip())
        if key in seen:
            continue
        seen.add(key)
        example = {
            "text": text.strip(),
            "language": "en",
            "meta": {
                **provenance(row),
                "source": row.get("example_source", row["source"]),
                "identifier": row["sense_id"],
                "type": "learner-example",
            },
        }
        sense["examples"].append(example)
        synset["examples"].append(example)
        counts["examples"] += 1


def build_resource(
    records, original_examples, required_example_senses=None,
    withheld_example_concepts=(),
):
    entries, senses, synsets = {}, {}, {}
    counts = Counter()
    seen_examples, seen_definitions, seen_irregular = set(), set(), {}
    for row in records:
        if row.get("unresolved_reason"):
            raise ValueError(
                f"unresolved content for {row.get('sense_id')}: "
                f"{row['unresolved_reason']}"
            )
        if row.get("synset_id") not in original_examples:
            raise ValueError(
                f"concept outside frequency inventory: {row.get('synset_id')}"
            )
        provenance(row)
        sense, synset = entities(row, entries, senses, synsets)
        for item in annotations(row, seen_irregular):
            key = (row["synset_id"], json.dumps(item, sort_keys=True))
            if key in seen_definitions:
                continue
            synset["definitions"].append(item)
            seen_definitions.add(key)
            counts["annotations"] += 1
            fields = json.loads(item["meta"]["description"])
            counts.update(
                key for key in (*FIELDS, "irregular_forms") if fields.get(key)
            )
            if item["text"] != row["base_definition"] and fields["scope"] != "word":
                counts["plain_language"] += 1
        if not original_examples[row["synset_id"]]:
            add_examples(row, sense, synset, seen_examples, counts)
    missing = [
        key
        for key, examples in original_examples.items()
        if not examples and not synsets.get(key, {}).get("examples")
        and key not in withheld_example_concepts
    ]
    if missing:
        raise ValueError(f"{len(missing)} concepts still lack examples: {missing[:5]}")
    missing_senses = [
        sid
        for sid in sorted(required_example_senses or ())
        if sid not in senses or not senses[sid][2]["examples"]
    ]
    if missing_senses:
        raise ValueError(
            f"{len(missing_senses)} target senses still lack examples: "
            f"{missing_senses[:5]}"
        )
    counts["concepts_with_added_examples"] = sum(
        bool(s["examples"]) for s in synsets.values()
    )
    counts["referenced_senses"] = len(senses)
    counts["referenced_words"] = len(entries)
    counts["referenced_synsets"] = len(synsets)
    counts["new_words"] = counts["new_senses"] = counts["new_synsets"] = 0
    resource = {
        "lmf_version": "1.4",
        "lexicons": [
            {
                "id": "rylo-en-learner",
                "version": "1.0",
                "label": "English learner enrichment for frequent words",
                "language": "en",
                "email": "amit@nagish.com",
                "license": (
                    "https://github.com/sign/wn/blob/main/extensions/"
                    "english-learner/SOURCE-LICENSES.txt"
                ),
                "url": "https://github.com/sign/wn/tree/main/extensions/english-learner",
                "meta": {
                    "description": (
                        "AI-generated learner text plus sourced WordNet labels. "
                        "Independent AI review is recorded per annotation; "
                        "AI review is not human review."
                    )
                },
                "extends": BASE,
                "entries": [entries[key] for key in sorted(entries)],
                "synsets": [synsets[key] for key in sorted(synsets)],
            }
        ],
    }
    return resource, dict(sorted(counts.items()))


def validate_identities(records, database):
    """Check source-sense membership against the read-only base database."""
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        definitions = {}
        for synset_id, text in conn.execute(
            "SELECT ss.id,d.definition FROM definitions d "
            "JOIN synsets ss ON ss.rowid=d.synset_rowid "
            "JOIN lexicons l ON l.rowid=d.lexicon_rowid "
            "WHERE l.specifier='omw-en:1.4'"
        ):
            definitions.setdefault(synset_id, set()).add(text)
        known = dict(
            conn.execute(
                "SELECT s.id, e.id || char(9) || ss.id FROM senses s "
                "JOIN entries e ON e.rowid=s.entry_rowid "
                "JOIN synsets ss ON ss.rowid=s.synset_rowid "
                "JOIN lexicons l ON l.rowid=s.lexicon_rowid "
                "WHERE l.specifier='omw-en:1.4'"
            )
        )
    for row in records:
        expected = row["word_id"] + "\t" + row["synset_id"]
        if known.get(row["sense_id"]) != expected:
            raise ValueError(f"unknown or mis-targeted base sense: {row['sense_id']}")
        if row["base_definition"] not in definitions.get(row["synset_id"], set()):
            raise ValueError(
                f"stale or incorrect reference definition: {row['sense_id']}"
            )


def validate_review(records):
    """Keep generation checkpoints out of the reviewed release package."""
    assessed = set()
    for row in records:
        if row.get("creator") == "WordNet" and row.get("source") == "omw-en:1.4":
            continue
        if not row.get("reviewer") or row.get("review_status") != "ai-reviewed":
            raise ValueError(f"missing independent AI review: {row['sense_id']}")
        assessed.add(row["sense_id"])
    return assessed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--records", type=Path, nargs="+", required=True)
    parser.add_argument(
        "--withheld", type=Path,
        help="Explicit sense IDs and reasons requiring further editorial review",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path.home() / ".wn_data/wn.db")
    args = parser.parse_args()
    inventory = list(read_records(args.inventory))
    original_examples = {row["synset_id"]: row["examples"] for row in inventory}
    records = [row for path in args.records for row in read_records(path)]
    validate_identities(records, args.database)
    assessed_senses = validate_review(records)
    expected_senses = {s["sense_id"] for r in inventory for s in r["senses"]}
    if {row["sense_id"] for row in records} - expected_senses:
        raise ValueError("release records contain senses outside the inventory")
    withheld = list(read_records(args.withheld)) if args.withheld else []
    withheld_ids = {row["sense_id"] for row in withheld}
    if len(withheld_ids) != len(withheld) or withheld_ids - expected_senses:
        raise ValueError("withheld senses must be unique members of the inventory")
    if withheld_ids & {row["sense_id"] for row in records}:
        raise ValueError("withheld senses must not be published in release records")
    if any(not isinstance(r.get("reason"), str) or not r["reason"].strip()
           for r in withheld):
        raise ValueError("every withheld sense requires an editorial reason")
    missing_senses = expected_senses - assessed_senses
    missing_senses -= withheld_ids
    if missing_senses:
        raise ValueError(f"{len(missing_senses)} target senses have not been assessed")
    required_examples = {
        s["sense_id"] for row in inventory if not row["examples"] for s in row["senses"]
    }
    concept_senses = {}
    for row in inventory:
        concept_senses.setdefault(row["synset_id"], set()).update(
            s["sense_id"] for s in row["senses"]
        )
    withheld_concepts = {
        ssid for ssid, senses in concept_senses.items() if senses <= withheld_ids
    }
    resource, counts = build_resource(
        records, original_examples, required_examples - withheld_ids,
        withheld_concepts,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    xml_path = (
        args.output.with_suffix("") if args.output.suffix == ".gz" else args.output
    )
    lmf.dump(resource, xml_path)
    if args.output.suffix == ".gz":
        args.output.write_bytes(gzip.compress(xml_path.read_bytes(), mtime=0))
        xml_path.unlink()
    report = {
        "base_lexicon": "omw-en:1.4",
        "extension": "rylo-en-learner:1.0",
        "frequency_cutoff": 5000,
        "matched_frequency_words": len({row["word"] for row in inventory}),
        "word_meaning_pairs": len(inventory),
        "unique_senses": len({s["sense_id"] for r in inventory for s in r["senses"]}),
        "unique_synsets": len(original_examples),
        "status": (
            "AI-generated, not human-reviewed; "
            "native labels retain WordNet provenance"
        ),
        "assessed_senses": len(assessed_senses),
        "review_status_counts": dict(Counter(
            row.get("review_status", "not-ai-reviewed") for row in records
        )),
        "withheld_senses": withheld,
        "counts": counts,
        "inputs": {
            str(p.name): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [args.inventory, *args.records,
                      *([args.withheld] if args.withheld else [])]
        },
        "extension_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    args.output.with_name("manifest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
