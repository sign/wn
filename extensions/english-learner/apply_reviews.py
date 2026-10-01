"""Quarantine failed semantic reviews without editing or silently approving text."""

import argparse
import hashlib
import importlib.util
import json
import lzma
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "learner_quality", HERE / "quality_gate.py"
)
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


def write_rows(path, rows):
    data = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in rows
    ).encode()
    path.write_bytes(lzma.compress(data) if path.suffix == ".xz" else data)


def select_reviewed(records, inventory, decisions, fixtures, calibration, withheld):
    items = quality.review_items(records, inventory)
    reviewed = quality.validate_decisions(items, decisions, require_accept=False)
    for run in sorted({d["review_run"] for d in decisions}):
        quality.validate_calibration(
            fixtures, [d for d in calibration if d["review_run"] == run]
        )
    blocked = {sid for sid, d in reviewed.items() if d["decision"] != "accept"}
    existing = {r["sense_id"] for r in withheld}
    if existing & {r["sense_id"] for r in records}:
        raise ValueError("previously withheld content must not re-enter without review")
    new_withheld = [
        {
            "sense_id": sid,
            "reason": "Semantic review: "
            + "; ".join(
                f"{issue['field']}: {issue['reason']}"
                for issue in reviewed[sid]["issues"]
            ),
        }
        for sid in sorted(blocked)
    ]
    accepted = [r for r in records if r["sense_id"] not in blocked]
    # Revised content cannot inherit its old review stamp. Only the validated
    # fresh approval above confers this checkpoint, including intentional removals.
    accepted = [
        {**r, "reviewer": quality.REVIEWER, "review_status": "ai-reviewed"}
        if r.get("requires_semantic_review")
        else r
        for r in accepted
    ]
    return {
        "accepted": accepted,
        "quarantined": [r for r in records if r["sense_id"] in blocked],
        "withheld": sorted([*withheld, *new_withheld], key=lambda r: r["sense_id"]),
        "reviews": [d for d in decisions if d["decision"] == "accept"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, nargs="+", required=True)
    parser.add_argument("--calibration", type=Path, nargs="+", required=True)
    parser.add_argument("--withheld", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    records = quality.read_jsonl(args.records)
    decisions = [d for p in args.decisions for d in quality.read_jsonl(p)]
    calibration = [d for p in args.calibration for d in quality.read_jsonl(p)]
    selected = select_reviewed(
        records,
        quality.read_jsonl(args.inventory),
        decisions,
        json.loads((HERE / "quality-calibration.json").read_text(encoding="utf-8")),
        calibration,
        quality.read_jsonl(args.withheld),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in {
        "reviewed-records.jsonl.xz": selected["accepted"],
        "quarantined-records.jsonl.xz": selected["quarantined"],
        "quality-reviews.jsonl.xz": selected["reviews"],
        "quality-audit.jsonl.xz": decisions,
        "quality-calibration-decisions.jsonl": calibration,
        "withheld.jsonl": selected["withheld"],
    }.items():
        write_rows(args.output_dir / name, rows)
    report = {
        "rubric_version": quality.RUBRIC_VERSION,
        "reviewer": quality.REVIEWER,
        "source_records_sha256": hashlib.sha256(args.records.read_bytes()).hexdigest(),
        "reviewed_senses": len(decisions),
        "decisions": dict(sorted(Counter(d["decision"] for d in decisions).items())),
        "issues_by_field": dict(
            sorted(Counter(i["field"] for d in decisions for i in d["issues"]).items())
        ),
        "withheld_senses": len(selected["withheld"]),
        "note": "AI review, not human verification or a measured accuracy guarantee.",
    }
    (args.output_dir / "quality-audit.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
