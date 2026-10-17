"""Load reviewed English examples after merging the Wikidata extension."""

import csv
import json
import re
from pathlib import Path

from wn._db import connect

DATA_DIR = Path(__file__).parent


def contains_word(text: str, word: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text, re.I) is not None


def add_examples(path: Path, lexicon: str = "omw-en:1.4") -> None:
    """Validate all targets, then add examples without replacing existing data."""
    records = json.loads(path.read_text(encoding="utf-8"))
    conn = connect()
    targets = []
    for record in records:
        word, sense, text = (record[key] for key in ("word", "sense", "example"))
        if not all(isinstance(value, str) and value.strip()
                   for value in (word, sense, text)):
            raise ValueError(f"Invalid example: {record!r}")
        if not contains_word(text, word) or not text.endswith((".", "!", "?")):
            raise ValueError(f"Example must be a sentence containing {word!r}")
        row = conn.execute(
            """SELECT s.rowid, s.synset_rowid, s.lexicon_rowid
               FROM senses s JOIN lexicons l ON l.rowid = s.lexicon_rowid
               WHERE s.id = ? AND l.specifier = ? AND EXISTS (
                   SELECT 1 FROM forms f WHERE f.entry_rowid = s.entry_rowid
                   AND lower(f.form) = lower(?))""",
            (sense, lexicon, word),
        ).fetchone()
        if row is None:
            raise ValueError(f"Missing sense/form in {lexicon}: {sense} / {word}")
        metadata = {
            "type": "learner-example",
            "identifier": sense,
            "creator": "OpenAI Codex",
            "source": "https://github.com/sign/wn/tree/v1.10.0/extensions/english-examples",
            "status": "unreviewed",
            "note": "AI-authored; not independently or human-reviewed",
        }
        if record.get("note"):
            metadata["description"] = record["note"]
        targets.append((*row, text, metadata))

    with conn:
        for sense_rowid, synset_rowid, lexicon_rowid, text, metadata in targets:
            for table, column, rowid in (
                ("sense_examples", "sense_rowid", sense_rowid),
                ("synset_examples", "synset_rowid", synset_rowid),
            ):
                conn.execute(
                    f"""INSERT INTO {table}
                        ({column}, lexicon_rowid, example, language, metadata)
                        SELECT ?, ?, ?, 'en', ? WHERE NOT EXISTS (
                            SELECT 1 FROM {table}
                            WHERE {column} = ? AND example = ?)""",
                    (rowid, lexicon_rowid, text, metadata, rowid, text),
                )


def check_coverage(path: Path, lexicon: str = "omw-en:1.4") -> int:
    """Require an example containing each ranked spelling, including its forms."""
    with path.open(encoding="utf-8") as stream:
        words = {row["word"] for row in csv.DictReader(stream, delimiter="\t")}
    covered = set()
    for form, text in connect().execute(
        """SELECT f.form, x.example FROM forms f
           JOIN senses s ON s.entry_rowid = f.entry_rowid
           JOIN synset_examples x ON x.synset_rowid = s.synset_rowid
           JOIN lexicons l ON l.rowid = s.lexicon_rowid
           WHERE l.specifier = ?""",
        (lexicon,),
    ):
        word = form.lower()
        if word in words and word not in covered and contains_word(text, word):
            covered.add(word)
    missing = words - covered
    if missing:
        raise ValueError(f"Words without examples: {', '.join(sorted(missing))}")
    return len(covered)


if __name__ == "__main__":
    add_examples(DATA_DIR / "examples.json")
    count = check_coverage(DATA_DIR / "top1000.tsv")
    print(f"English example coverage: {count}/{count} ranked words")
