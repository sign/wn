#!/usr/bin/env python3
"""Merge a WN-LMF lexicon extension into its base lexicon.

`wn.add()` stores an extension as a separate lexicon row, which means
queries against the base lexicon won't see the extension's entries.
This script loads the extension normally and then rewrites the
``lexicon_rowid`` columns of every content table so the extension's
rows appear under the base lexicon — leaving one lexicon per language
in the database.

See https://github.com/goodmami/wn/issues/304 for the original motivation.

Usage::

    python merge_extension.py path/to/extension.xml [more.xml ...]
"""
from __future__ import annotations

import logging
import re
import sys
from contextlib import contextmanager
from pathlib import Path

import wn
from wn import lmf
from wn._db import connect
from wn._util import format_lexicon_specifier

log = logging.getLogger("wn")

_FIRST_ENTRY_ID_RE = re.compile(rb'<LexicalEntry\b[^>]*\bid="([^"]+)"')

# Tables with a ``lexicon_rowid`` column. Keep in sync with wn/schema.sql.
_LEXICON_OWNED_TABLES = (
    "entries",
    "forms",
    "pronunciations",
    "tags",
    "synsets",
    "synset_relations",
    "definitions",
    "synset_examples",
    "senses",
    "sense_relations",
    "sense_synset_relations",
    "sense_examples",
    "counts",
    "syntactic_behaviours",
)

# Tables in _LEXICON_OWNED_TABLES that lack an index on lexicon_rowid in
# the shipped schema. We create a temporary index over the bulk merge so
# each UPDATE is O(rows-to-update) instead of O(table-size).
_UNINDEXED_TABLES = (
    "entries",
    "pronunciations",
    "tags",
    "synsets",
    "synset_relations",
    "definitions",
    "synset_examples",
    "senses",
    "sense_relations",
    "sense_synset_relations",
    "sense_examples",
    "counts",
)


def _get_lexicon_rowid(cur, specifier: str) -> int | None:
    row = cur.execute(
        "SELECT rowid FROM lexicons WHERE specifier = ?",
        (specifier,),
    ).fetchone()
    return row[0] if row else None


def _first_entry_id(xml_path: Path) -> str | None:
    with open(xml_path, "rb") as fh:
        match = _FIRST_ENTRY_ID_RE.search(fh.read())
    return match.group(1).decode("utf-8") if match else None


def _is_already_merged(cur, xml_path: Path, base_rowid: int) -> bool:
    entry_id = _first_entry_id(xml_path)
    if entry_id is None:
        return False
    return (
        cur.execute(
            "SELECT 1 FROM entries WHERE id = ? AND lexicon_rowid = ?",
            (entry_id, base_rowid),
        ).fetchone()
        is not None
    )


def merge_extension(xml_path: Path) -> None:
    """Add *xml_path* and absorb it into its base lexicon."""
    infos = lmf.scan_lexicons(xml_path)
    if not infos:
        log.warning("%s: no lexicons found, skipping", xml_path)
        return

    info = infos[0]
    extends = info.get("extends")
    if not extends:
        log.info("%s: not a lexicon extension, loading as-is", xml_path)
        wn.add(xml_path, progress_handler=None)
        return

    ext_spec = format_lexicon_specifier(info["id"], info["version"])
    base_spec = format_lexicon_specifier(extends["id"], extends["version"])

    conn = connect()
    cur = conn.cursor()

    base_rowid = _get_lexicon_rowid(cur, base_spec)
    if base_rowid is None:
        log.info(
            "skipping %s: base lexicon %s is not in the database",
            ext_spec,
            base_spec,
        )
        return

    if _is_already_merged(cur, xml_path, base_rowid):
        log.info("%s already merged into %s", ext_spec, base_spec)
        return

    wn.add(xml_path, progress_handler=None)

    ext_rowid = _get_lexicon_rowid(cur, ext_spec)
    if ext_rowid is None:
        raise RuntimeError(f"failed to add extension {ext_spec}")

    with conn:
        for table in _LEXICON_OWNED_TABLES:
            cur.execute(
                f"UPDATE {table} SET lexicon_rowid = ? WHERE lexicon_rowid = ?",
                (base_rowid, ext_rowid),
            )
        cur.execute(
            "DELETE FROM lexicon_extensions WHERE extension_rowid = ?",
            (ext_rowid,),
        )
        cur.execute(
            "DELETE FROM lexicon_dependencies WHERE dependent_rowid = ?",
            (ext_rowid,),
        )
        cur.execute("DELETE FROM lexicons WHERE rowid = ?", (ext_rowid,))

    log.info("Merged %s into %s", ext_spec, base_spec)


@contextmanager
def _bulk_merge_indexes(conn):
    for table in _UNINDEXED_TABLES:
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS "
            f"tmp_merge_{table}_lex ON {table}(lexicon_rowid)"
        )
    try:
        yield
    finally:
        for table in _UNINDEXED_TABLES:
            conn.execute(f"DROP INDEX IF EXISTS tmp_merge_{table}_lex")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1

    with _bulk_merge_indexes(connect()):
        for arg in argv:
            path = Path(arg)
            if not path.exists():
                log.warning("skipping missing path: %s", path)
                continue
            merge_extension(path)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main(sys.argv[1:]))
