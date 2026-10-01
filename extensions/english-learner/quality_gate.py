"""Content-bound semantic review for the English learner release.

Review decisions attest to exact content, not to a mutable sense ID or a model
name copied into a row. This gate cannot prove linguistic truth; it makes
missing, stale, negative and uncalibrated reviews release-blocking.
"""

import argparse
import hashlib
import json
import lzma
import re
from collections import defaultdict
from pathlib import Path

RUBRIC_VERSION = "exact-sense-2"
REVIEWER = "gpt-6-astra"
FIELDS = (
    "plain_language",
    "examples",
    "domains",
    "register",
    "usage",
    "grammar_notes",
    "irregular_forms",
    "usage_tips",
)
RUBRIC = """Independently audit ALL proposed learner fields against the exact lemma,
part of speech and WordNet meaning. Prior generation/review stamps are not
quality evidence. Do not silently repair a record and then accept its old hash.

For EVERY example, determine the grammatical role of the target word in that
sentence and whether it expresses this precise sense. Merely containing the
word is insufficient. A noun medical is not illustrated by medical examination;
a nominal football run must not receive the verb's conjugation. Distinguish
attributive adjectives, nouns, participles, homographs, transitivity and closely
related senses (replacement by substitution versus replenishment).

Check every paraphrase for lost distinctions, added claims, wrong entity and
circular or unnatural wording. Check countability, complements, register,
collocations and irregular forms against THIS sense, not the lemma generally.
Word-scoped forms must be valid across the word's senses. Do not force current
meanings onto archaic/specialist senses. Reject unsupported factual or normative
claims and advice (including invented register, diagnostic rules and legal
claims). Native WordNet labels are separately attributed; assess new claims.

Accept only if ALL proposed fields are defensible, useful and idiomatic for
this exact sense. Reject clear errors with field-specific reasons. Use uncertain
when a specialist or factual assertion cannot be justified from the context.
Do not over-reject ordinary inflections, proper names or explicitly explained
historical/slur usage. Empty fields are intentional; do not demand extra prose.
Do not give an entire batch a default pass. Read every item and provide a brief
sense-specific rationale. Return each exact sense_id/input_sha256 with decision
accept/reject/uncertain, rationale, and issues [{field, reason}]. No rewrites.
"""


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def read_jsonl(path):
    opener = lzma.open if str(path).endswith(".xz") else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def native(row):
    return row.get("creator") == "WordNet" and row.get("source") == "omw-en:1.4"


def validate_native(records, inventory):
    """Only unchanged native topic links may bypass model review."""
    topics = defaultdict(set)
    for row in inventory:
        for rel in row.get("relations", []):
            if rel["type"] == "domain_topic" and rel.get("forms"):
                topics[row["synset_id"]].add((rel["forms"][0], rel["target_synset_id"]))
    for row in records:
        if not native(row):
            continue
        if any(row.get(field) for field in FIELDS if field != "domains"):
            raise ValueError(
                f"native provenance cannot bypass review: {row['sense_id']}"
            )
        evidence = {
            (e["label"], e["synset_id"]) for e in row.get("domain_evidence", [])
        }
        if (
            set(row.get("domains", [])) != {label for label, _ in evidence}
            or not evidence <= topics[row["synset_id"]]
        ):
            raise ValueError(f"unverified native topic labels: {row['sense_id']}")


def review_contexts(inventory):
    contexts = {}
    for concept in inventory:
        for sense in concept["senses"]:
            context = {
                "word_id": sense["entry_id"],
                "synset_id": concept["synset_id"],
                "lemma": sense["lemma"],
                "pos": sense["pos"],
                "definitions": concept["definitions"],
                "synonyms": concept["synonyms"],
                "existing_examples": concept["examples"],
                "syntactic_frames": sense.get("syntactic_frames", []),
            }
            sid = sense["sense_id"]
            if sid in contexts and contexts[sid] != context:
                raise ValueError(f"conflicting inventory context: {sid}")
            contexts[sid] = context
    return contexts


def review_items(records, inventory):
    contexts = review_contexts(inventory)
    validate_native(records, inventory)
    grouped = defaultdict(list)
    for row in records:
        context = contexts.get(row["sense_id"])
        if context is None:
            raise ValueError(f"no review context: {row['sense_id']}")
        if (
            row.get("word_id") != context["word_id"]
            or row.get("synset_id") != context["synset_id"]
            or row.get("base_definition") not in context["definitions"]
        ):
            raise ValueError(f"source identity differs from context: {row['sense_id']}")
        if native(row):
            continue
        fields = {key: row[key] for key in FIELDS if row.get(key)}
        removal = (
            row.get("correction_method") == "remove flagged fields"
            and isinstance(row.get("correction_of"), str)
            and re.fullmatch(r"[0-9a-f]{64}", row["correction_of"])
        )
        needs_author = (
            row.get("requires_semantic_review") and fields and not removal
        ) or row.get("prompt_version") == "english-learner-7"
        if needs_author and (
            not isinstance(row.get("author_run"), str) or not row["author_run"].strip()
        ):
            raise ValueError(
                f"generated correction requires author_run: {row['sense_id']}"
            )
        if not fields and not row.get("requires_semantic_review"):
            continue
        grouped[row["sense_id"]].append(
            {
                "scope": row.get("scope", "sense"),
                "irregular_forms_scope": row.get("irregular_forms_scope", "sense"),
                **(
                    {"plain_language_scope": row.get("plain_language_scope", "sense")}
                    if row.get("scope", "sense") != "sense"
                    or row.get("plain_language_scope", "sense") != "sense"
                    else {}
                ),
                **({"author_run": row["author_run"]} if row.get("author_run") else {}),
                "fields": fields,
            }
        )
    items = []
    for sid, annotations in sorted(grouped.items()):
        if sid not in contexts:
            raise ValueError(f"no review context: {sid}")
        payload = {
            "sense_id": sid,
            **contexts[sid],
            "annotations": sorted(annotations, key=digest),
        }
        items.append(
            {
                "sense_id": sid,
                "input_sha256": digest(
                    {
                        "rubric_version": RUBRIC_VERSION,
                        "rubric": RUBRIC,
                        "content": payload,
                    }
                ),
                "content": payload,
            }
        )
    return items


def validate_decision(decision, require_accept):
    sid = decision["sense_id"]
    if (
        decision.get("reviewer") != REVIEWER
        or decision.get("rubric_version") != RUBRIC_VERSION
    ):
        raise ValueError(f"wrong reviewer or rubric: {sid}")
    if (
        not isinstance(decision.get("rationale"), str)
        or not decision["rationale"].strip()
    ):
        raise ValueError(f"missing review rationale: {sid}")
    if (
        not isinstance(decision.get("review_run"), str)
        or not decision["review_run"].strip()
    ):
        raise ValueError(f"missing review run: {sid}")
    verdict = decision.get("decision")
    issues = decision.get("issues")
    if verdict not in ("accept", "reject", "uncertain") or not isinstance(issues, list):
        raise ValueError(f"invalid review decision: {sid}")
    if any(
        not isinstance(issue, dict)
        or issue.get("field") not in FIELDS
        or not isinstance(issue.get("reason"), str)
        or not issue["reason"].strip()
        for issue in issues
    ):
        raise ValueError(f"invalid review issue: {sid}")
    if (verdict == "accept") != (len(issues) == 0):
        raise ValueError(f"inconsistent review issues: {sid}")
    if require_accept and verdict != "accept":
        raise ValueError(f"unresolved semantic review: {sid}")


def validate_decisions(items, decisions, *, require_accept=True):
    expected = {item["sense_id"]: item for item in items}
    if len(expected) != len(items):
        raise ValueError("duplicate review input")
    for item in items:
        content_hash = digest(
            {
                "rubric_version": RUBRIC_VERSION,
                "rubric": RUBRIC,
                "content": item["content"],
            }
        )
        if item["input_sha256"] != content_hash:
            raise ValueError("review input hash does not match content")
    seen = {}
    for decision in decisions:
        sid = decision.get("sense_id")
        if sid in seen or sid not in expected:
            raise ValueError(f"duplicate or unknown review: {sid}")
        seen[sid] = decision
        if decision.get("input_sha256") != expected[sid]["input_sha256"]:
            raise ValueError(f"stale review content: {sid}")
        validate_decision(decision, require_accept)
        if any(
            annotation.get("author_run") == decision["review_run"]
            for annotation in expected[sid]["content"]["annotations"]
        ):
            raise ValueError(f"author cannot approve their own correction: {sid}")
    if set(expected) != set(seen):
        raise ValueError(f"{len(set(expected) - set(seen))} missing semantic reviews")
    return seen


def validate_calibration(fixtures, decisions):
    if (
        len(fixtures) < 12
        or sum(f.get("expected_accept") is True for f in fixtures) < 4
        or sum(f.get("expected_accept") is False for f in fixtures) < 8
    ):
        raise ValueError("incomplete calibration fixtures")
    seen = validate_decisions(fixtures, decisions, require_accept=False)
    failures = [
        f["sense_id"]
        for f in fixtures
        if (seen[f["sense_id"]]["decision"] == "accept") != f["expected_accept"]
    ]
    if failures:
        raise ValueError(f"semantic reviewer failed calibration: {failures}")
    return {
        "cases": len(fixtures),
        "passed": len(fixtures),
        "fixtures_sha256": digest(fixtures),
        "decisions_sha256": digest(decisions),
    }


def validate_release(records, inventory, decisions, fixtures, calibration):
    items = review_items(records, inventory)
    validate_decisions(items, decisions)
    runs = {d["review_run"] for d in decisions}
    result = {}
    for run in sorted(runs):
        result[run] = validate_calibration(
            fixtures, [d for d in calibration if d.get("review_run") == run]
        )
    return {
        "status": "passed",
        "rubric_version": RUBRIC_VERSION,
        "reviewer": REVIEWER,
        "reviewed_senses": len(items),
        "content_sha256": digest(items),
        "decisions_sha256": digest(decisions),
        "calibration": result,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--calibration-output",
        type=Path,
        help="Write calibration inputs without their expected verdicts",
    )
    args = parser.parse_args()
    items = review_items(read_jsonl(args.records), read_jsonl(args.inventory))
    args.output.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items),
        encoding="utf-8",
    )
    if args.calibration_output:
        fixtures = json.loads(
            Path(__file__)
            .with_name("quality-calibration.json")
            .read_text(encoding="utf-8")
        )
        args.calibration_output.write_text(
            "".join(json.dumps(blind_fixture(item)) + "\n" for item in fixtures),
            encoding="utf-8",
        )
    print(f"Prepared {len(items)} exact-sense review inputs")


def blind_fixture(item):
    return {key: item[key] for key in ("sense_id", "input_sha256", "content")}


def compact_inventory(inventory):
    """Keep the original reference context needed to reproduce every decision."""
    concepts = {}
    for row in inventory:
        concept = concepts.setdefault(
            row["synset_id"],
            {
                "synset_id": row["synset_id"],
                "definitions": row["definitions"],
                "examples": row["examples"],
                "synonyms": row["synonyms"],
                "relations": [
                    r for r in row.get("relations", []) if r["type"] == "domain_topic"
                ],
                "senses": {},
            },
        )
        for sense in row["senses"]:
            concept["senses"][sense["sense_id"]] = {
                key: sense[key]
                for key in ("sense_id", "entry_id", "lemma", "pos", "syntactic_frames")
                if key in sense
            }
    return [
        {
            **concept,
            "senses": [concept["senses"][sid] for sid in sorted(concept["senses"])],
        }
        for _, concept in sorted(concepts.items())
    ]


if __name__ == "__main__":
    main()
