"""Prepare targeted, unreviewed repairs from exact-content review findings."""

import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "learner_quality", HERE / "quality_gate.py"
)
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


def prepare(records, inventory, decisions, withheld):
    items = {r["sense_id"]: r for r in quality.review_items(records, inventory)}
    ids = {d["sense_id"] for d in decisions}
    if ids - items.keys():
        raise ValueError("correction review references unknown content")
    quality.validate_decisions(
        [items[sid] for sid in sorted(ids)], decisions, require_accept=False
    )
    corrections = {
        d["sense_id"]: {
            "previous_input_sha256": d["input_sha256"],
            "prior_annotations": items[d["sense_id"]]["content"]["annotations"],
            "issues": d["issues"],
        }
        for d in decisions
        if d["decision"] != "accept"
    }
    for row in withheld:
        if row["sense_id"] in items:
            raise ValueError("withheld sense also has candidate content")
        corrections[row["sense_id"]] = {
            "prior_annotations": [],
            "issues": [{"field": "examples", "reason": row["reason"]}],
        }
    selected = {}
    for row in sorted(inventory, key=lambda r: r["frequency_rank"]):
        for sense in row["senses"]:
            sid = sense["sense_id"]
            if sid in corrections and sid not in selected:
                selected[sid] = {
                    **row,
                    "senses": [sense],
                    "correction": corrections[sid],
                }
    if selected.keys() != corrections.keys():
        raise ValueError("correction sense missing from inventory")
    return list(selected.values())


def remove_flagged_fields(records, decisions):
    """Remove unsupported optional text; the result still needs fresh review.

    Missing examples are left for an author, never replaced by a template.
    Call prepare first to validate the decisions against the original content.
    """
    failed = {d["sense_id"]: d for d in decisions if d["decision"] != "accept"}
    result = []
    for row in records:
        review = failed.get(row["sense_id"])
        if review is None or quality.native(row):
            result.append(row)
            continue
        removed = {issue["field"] for issue in review["issues"]}
        revised = {k: v for k, v in row.items() if k not in removed}
        revised.pop("reviewer", None)
        revised.pop("review_status", None)
        revised.update(
            status="unreviewed",
            requires_semantic_review=True,
            correction_of=review["input_sha256"],
            correction_method="remove flagged fields",
        )
        result.append(revised)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, nargs="+", required=True)
    parser.add_argument("--withheld", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = prepare(
        quality.read_jsonl(args.records),
        quality.read_jsonl(args.inventory),
        [d for path in args.decisions for d in quality.read_jsonl(path)],
        quality.read_jsonl(args.withheld) if args.withheld else [],
    )
    args.output.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    print(f"Prepared {len(rows)} senses for correction; no reviews conferred")


if __name__ == "__main__":
    main()
