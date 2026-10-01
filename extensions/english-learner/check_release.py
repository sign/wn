"""Verify the committed source, reviews and compiled package agree; no model call."""

import argparse
import gzip
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

from wn import lmf

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "learner_build", HERE / "build_extension.py"
)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
quality = builder.quality


def check_release(directory):
    records_path = directory / "reviewed-records.jsonl.xz"
    reviews_path = directory / "quality-reviews.jsonl.xz"
    calibration_path = directory / "quality-calibration-decisions.jsonl"
    context_path = directory / "quality-context.jsonl.xz"
    withheld_path = directory / "withheld.jsonl"
    fixtures_path = directory / "quality-calibration.json"
    package_path = directory / "rylo-en-learner.xml.gz"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for path in (
        records_path,
        reviews_path,
        calibration_path,
        context_path,
        withheld_path,
        fixtures_path,
    ):
        if (
            manifest["inputs"].get(path.name)
            != hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            raise ValueError(f"changed release input: {path.name}")
    if (
        manifest["extension_sha256"]
        != hashlib.sha256(package_path.read_bytes()).hexdigest()
    ):
        raise ValueError("changed compiled extension")
    records = quality.read_jsonl(records_path)
    inventory = quality.read_jsonl(context_path)
    gate = quality.validate_release(
        records,
        inventory,
        quality.read_jsonl(reviews_path),
        json.loads(fixtures_path.read_text(encoding="utf-8")),
        quality.read_jsonl(calibration_path),
    )
    if manifest.get("quality_gate") != gate:
        raise ValueError("manifest quality gate disagrees with exact-content decisions")
    withheld = quality.read_jsonl(withheld_path)
    withheld_ids = {r["sense_id"] for r in withheld}
    expected = {s["sense_id"] for r in inventory for s in r["senses"]}
    if (
        len(withheld_ids) != len(withheld)
        or withheld_ids - expected
        or any(not r.get("reason", "").strip() for r in withheld)
        or withheld_ids & {r["sense_id"] for r in records}
    ):
        raise ValueError("invalid withheld scope")
    assessed = builder.validate_review(records)
    if assessed | withheld_ids != expected:
        raise ValueError("release target coverage changed")
    if manifest["withheld_senses"] != withheld:
        raise ValueError("manifest withheld senses changed")
    examples = {row["synset_id"]: row["examples"] for row in inventory}
    required = {
        s["sense_id"] for r in inventory if not r["examples"] for s in r["senses"]
    }
    excluded = {
        r["synset_id"]
        for r in inventory
        if {s["sense_id"] for s in r["senses"]} <= withheld_ids
    }
    resource, counts = builder.build_resource(
        builder.mark_semantic_review(records),
        examples,
        required - withheld_ids,
        excluded,
    )
    if counts != manifest["counts"]:
        raise ValueError("manifest content counts changed")
    # Recompile instead of trusting an editable status/hash in the manifest.
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "extension.xml"
        lmf.dump(resource, path)
        original = (
            gzip.decompress(package_path.read_bytes())
            .decode("utf-8")
            .replace("\r\n", "\n")
        )
        if path.read_text(encoding="utf-8") != original:
            raise ValueError("compiled extension differs from approved source")
    return gate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=HERE)
    args = parser.parse_args()
    print(json.dumps(check_release(args.directory), indent=2))


if __name__ == "__main__":
    main()
