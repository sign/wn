"""Prepare generation inputs from installed WordNet and existing candidate text.

This script only reads the installed database. Candidate language-model output is
kept separate from original WordNet evidence and is never treated as reviewed.
"""

import argparse
import hashlib
import json
import re
import sqlite3
import tarfile
import unicodedata
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def normalize(value):
    return re.sub(
        "[\u0300-\u036f\u0591-\u05c7]", "", unicodedata.normalize("NFD", value)
    ).lower()


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def rows(connection, sql, params=()):
    return [dict(row) for row in connection.execute(sql, params)]


def group(items, key):
    result = defaultdict(list)
    for item in items:
        item = dict(item)
        result[item.pop(key)].append(item)
    return result


def source_data(connection, lexicon):
    definitions = group(
        rows(
            connection,
            """
        SELECT synset_rowid, definition FROM definitions
        WHERE lexicon_rowid=? ORDER BY rowid
    """,
            (lexicon,),
        ),
        "synset_rowid",
    )
    examples = group(
        rows(
            connection,
            """
        SELECT synset_rowid, example FROM synset_examples
        WHERE lexicon_rowid=? ORDER BY rowid
    """,
            (lexicon,),
        ),
        "synset_rowid",
    )
    forms = group(
        rows(
            connection,
            """
        SELECT entry_rowid, form, rank FROM forms
        WHERE lexicon_rowid=? ORDER BY rank, rowid
    """,
            (lexicon,),
        ),
        "entry_rowid",
    )
    tags = group(
        rows(
            connection,
            """
        SELECT f.entry_rowid, f.form, t.tag, t.category
        FROM tags t JOIN forms f ON f.rowid=t.form_rowid
        WHERE t.lexicon_rowid=? ORDER BY f.rowid,t.rowid
    """,
            (lexicon,),
        ),
        "entry_rowid",
    )
    frames = group(
        rows(
            connection,
            """
        SELECT s.sense_rowid, b.frame FROM syntactic_behaviour_senses s
        JOIN syntactic_behaviours b ON b.rowid=s.syntactic_behaviour_rowid
        WHERE b.lexicon_rowid=? ORDER BY b.rowid
    """,
            (lexicon,),
        ),
        "sense_rowid",
    )
    sense_examples = group(
        rows(
            connection,
            """
        SELECT sense_rowid, example FROM sense_examples
        WHERE lexicon_rowid=? ORDER BY rowid
    """,
            (lexicon,),
        ),
        "sense_rowid",
    )
    adjpositions = group(
        rows(
            connection,
            """
        SELECT a.sense_rowid, a.adjposition FROM adjpositions a
        JOIN senses s ON s.rowid=a.sense_rowid
        WHERE s.lexicon_rowid=? ORDER BY a.rowid
    """,
            (lexicon,),
        ),
        "sense_rowid",
    )
    relations = group(
        rows(
            connection,
            """
        SELECT r.source_rowid, t.type, ss.rowid AS target_rowid,
               ss.id AS target_synset_id
        FROM synset_relations r
        JOIN relation_types t ON t.rowid=r.type_rowid
        JOIN synsets ss ON ss.rowid=r.target_rowid
        WHERE r.lexicon_rowid=? AND t.type IN
          ('domain_topic','domain_region','exemplifies',
           'hypernym','instance_hypernym')
        ORDER BY r.rowid
    """,
            (lexicon,),
        ),
        "source_rowid",
    )
    synset_forms = group(
        rows(
            connection,
            """
        SELECT s.synset_rowid, f.form FROM senses s JOIN forms f
        ON f.entry_rowid=s.entry_rowid AND f.rank=0
        WHERE s.lexicon_rowid=? ORDER BY s.synset_rank,s.rowid
    """,
            (lexicon,),
        ),
        "synset_rowid",
    )
    for related in relations.values():
        for relation in related:
            target = relation.pop("target_rowid")
            relation["forms"] = [f["form"] for f in synset_forms[target]]
            relation["definitions"] = [d["definition"] for d in definitions[target]]
    return (
        definitions,
        examples,
        forms,
        tags,
        frames,
        sense_examples,
        adjpositions,
        relations,
        synset_forms,
    )


def build_inventory(connection, lexicon, ranks):
    (
        definitions,
        examples,
        forms,
        tags,
        frames,
        sense_examples,
        adjpositions,
        relations,
        synset_forms,
    ) = source_data(connection, lexicon)
    pairs = {}
    senses = rows(
        connection,
        """
        SELECT s.rowid AS sense_rowid, s.id AS sense_id,
               s.entry_rowid, e.id AS entry_id, e.pos AS entry_pos,
               s.synset_rowid, ss.id AS synset_id, ss.pos, l.name AS lexfile
        FROM senses s JOIN entries e ON e.rowid=s.entry_rowid
        JOIN synsets ss ON ss.rowid=s.synset_rowid
        LEFT JOIN lexfiles l ON l.rowid=ss.lexfile_rowid
        WHERE s.lexicon_rowid=? ORDER BY s.entry_rowid,s.entry_rank,s.rowid
    """,
        (lexicon,),
    )
    for sense in senses:
        entry = sense["entry_rowid"]
        matching = defaultdict(list)
        for form in forms[entry]:
            normalized = normalize(form["form"])
            if normalized in ranks:
                matching[normalized].append(form["form"])
        for word, matching_forms in matching.items():
            synset = sense["synset_rowid"]
            key = (word, sense["synset_id"])
            pair = pairs.setdefault(
                key,
                {
                    "frequency_rank": ranks[word],
                    "word": word,
                    "synset_id": sense["synset_id"],
                    "pos": sense["pos"],
                    "lexfile": sense["lexfile"],
                    "definitions": [d["definition"] for d in definitions[synset]],
                    "examples": [e["example"] for e in examples[synset]],
                    "synonyms": list(
                        dict.fromkeys(f["form"] for f in synset_forms[synset])
                    ),
                    "relations": relations[synset],
                    "senses": [],
                },
            )
            pair["senses"].append(
                {
                    "sense_id": sense["sense_id"],
                    "entry_id": sense["entry_id"],
                    "pos": sense["entry_pos"],
                    "lemma": next(f["form"] for f in forms[entry] if f["rank"] == 0),
                    "matching_forms": matching_forms,
                    "forms": forms[entry],
                    "tags": tags[entry],
                    "syntactic_frames": [
                        f["frame"] for f in frames[sense["sense_rowid"]]
                    ],
                    "adjective_positions": [
                        p["adjposition"] for p in adjpositions[sense["sense_rowid"]]
                    ],
                    "examples": [
                        e["example"] for e in sense_examples[sense["sense_rowid"]]
                    ],
                    "candidates": [],
                }
            )
    return sorted(pairs.values(), key=lambda r: (r["frequency_rank"], r["synset_id"]))


def attach_candidates(inventory, archive):
    wanted = defaultdict(list)
    for pair in inventory:
        for sense in pair["senses"]:
            for form in sense["forms"]:
                wanted[(form["form"], pair["synset_id"])].append(sense)
    wanted_words = {word for word, _ in wanted}
    with tarfile.open(archive, "r:xz") as stream:
        for member in stream:
            if not member.isfile() or not member.name.endswith(".json"):
                continue
            word = Path(member.name).stem
            if word not in wanted_words:
                continue
            with stream.extractfile(member) as document:
                candidates = json.load(document)
            for candidate in candidates:
                for sense in wanted.get((word, candidate["id"]), []):
                    sense["candidates"].append(
                        {
                            "source_member": member.name,
                            "source_word": word,
                            "source_definition": candidate.get("source_definition"),
                            "plain_language": candidate.get("alternative_definition"),
                            "examples": candidate.get("examples", []),
                            "status": "unreviewed",
                        }
                    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path.home() / ".wn_data/wn.db")
    parser.add_argument("--lexicon", default="omw-en:1.4")
    parser.add_argument(
        "--frequency", type=Path, default=HERE / "frequency-en-5000.json"
    )
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    words = json.loads(args.frequency.read_text())
    ranks = {word: rank for rank, word in enumerate(words, 1)}
    connection = sqlite3.connect(
        args.database.resolve().as_uri() + "?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    lexicon = connection.execute(
        "SELECT rowid FROM lexicons WHERE specifier=?", (args.lexicon,)
    ).fetchone()
    if lexicon is None:
        parser.error(f"Install {args.lexicon} before preparing its inventory.")
    inventory = build_inventory(connection, lexicon["rowid"], ranks)
    connection.close()
    if args.candidates:
        attach_candidates(inventory, args.candidates)
    matched_words = {row["word"] for row in inventory}
    missing = [row for row in inventory if not any(row["examples"])]
    summary = {
        "schema_version": 1,
        "lexicon": args.lexicon,
        "frequency_sha256": digest(args.frequency),
        "frequency_count": len(words),
        "matched_words": len(matched_words),
        "word_meaning_pairs": len(inventory),
        "unique_synsets": len({r["synset_id"] for r in inventory}),
        "unique_senses": len({s["sense_id"] for r in inventory for s in r["senses"]}),
        "missing_example_pairs": len(missing),
        "missing_example_synsets": len({r["synset_id"] for r in missing}),
        "pairs_with_candidate_text": sum(
            any(s["candidates"] for s in r["senses"]) for r in inventory
        ),
        "candidate_archive_sha256": digest(args.candidates)
        if args.candidates
        else None,
        "candidate_matching": "Exact stored form (including case) and synset ID.",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "inventory.jsonl").open("w") as stream:
        for item in inventory:
            stream.write(
                json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    (args.output / "unmatched-words.json").write_text(
        json.dumps(
            [
                {"frequency_rank": ranks[word], "word": word}
                for word in words
                if word not in matched_words
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
