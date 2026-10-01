"""A stale stamp, incomplete critic or failed calibration must not release text."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / "extensions/english-learner"
SPEC = importlib.util.spec_from_file_location(
    "learner_quality", ROOT / "quality_gate.py"
)
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


@pytest.fixture
def source():
    records = [
        {
            "sense_id": "love-1-n",
            "word_id": "love-n",
            "synset_id": "1-n",
            "base_definition": "a beloved person",
            "plain_language": "Someone you love.",
            "examples": ["Hello, my love."],
            "creator": "generator",
            "source": "generated",
        }
    ]
    inventory = [
        {
            "synset_id": "1-n",
            "definitions": ["a beloved person"],
            "examples": [],
            "synonyms": ["love", "beloved"],
            "relations": [
                {
                    "type": "domain_topic",
                    "target_synset_id": "topic-1-n",
                    "forms": ["relationships"],
                }
            ],
            "senses": [
                {
                    "sense_id": "love-1-n",
                    "entry_id": "love-n",
                    "lemma": "love",
                    "pos": "n",
                    "syntactic_frames": [],
                }
            ],
        }
    ]
    return records, inventory


def decision(item, verdict="accept", run="test-run"):
    return {
        "sense_id": item["sense_id"],
        "input_sha256": item["input_sha256"],
        "reviewer": quality.REVIEWER,
        "review_run": run,
        "rubric_version": quality.RUBRIC_VERSION,
        "decision": verdict,
        "rationale": "The noun names a beloved person.",
        "issues": []
        if verdict == "accept"
        else [{"field": "examples", "reason": "Target is used as a verb."}],
    }


def calibration(run="test-run"):
    fixtures = json.loads(
        (ROOT / "quality-calibration.json").read_text(encoding="utf-8")
    )
    return fixtures, [
        decision(i, "accept" if i["expected_accept"] else "reject", run)
        for i in fixtures
    ]


def test_correction_author_requires_an_independent_reviewer(source):
    records, inventory = source
    records[0]["author_run"] = "author-run"
    item = quality.review_items(records, inventory)[0]
    with pytest.raises(ValueError, match="author cannot approve"):
        quality.validate_decisions([item], [decision(item, run="author-run")])
    quality.validate_decisions([item], [decision(item, run="independent-run")])
    records[0]["author_run"] = "another-author"
    changed = quality.review_items(records, inventory)[0]
    with pytest.raises(ValueError, match="stale review content"):
        quality.validate_decisions([changed], [decision(item, run="independent-run")])


def test_paraphrase_scope_change_cannot_reuse_sense_review(source):
    records, inventory = source
    original = quality.review_items(records, inventory)[0]
    records[0]["plain_language_scope"] = "synset"
    changed = quality.review_items(records, inventory)[0]
    assert changed["content"]["annotations"][0]["plain_language_scope"] == "synset"
    with pytest.raises(ValueError, match="stale review content"):
        quality.validate_decisions([changed], [decision(original)])
    # Paraphrases have their own scope, independent of the other learner fields.
    records[0].pop("plain_language_scope")
    records[0]["scope"] = "synset"
    scoped = quality.review_items(records, inventory)[0]
    assert scoped["content"]["annotations"][0]["plain_language_scope"] == "sense"


def test_release_requires_exact_content_approval_and_calibrated_run(source):
    records, inventory = source
    items = quality.review_items(records, inventory)
    fixtures, controls = calibration()
    result = quality.validate_release(
        records, inventory, [decision(items[0])], fixtures, controls
    )
    assert result["reviewed_senses"] == 1
    assert result["calibration"]["test-run"]["passed"] == 12
    with pytest.raises(ValueError, match="missing semantic reviews"):
        quality.validate_release(records, inventory, [], fixtures, controls)
    with pytest.raises(ValueError, match="missing semantic reviews"):
        quality.validate_release(records, inventory, [decision(items[0])], fixtures, [])


@pytest.mark.parametrize(
    "change", ["text", "scope", "definition", "pos", "lemma", "forms_scope"]
)
def test_content_or_context_change_invalidates_old_review(source, change):
    records, inventory = source
    previous = decision(quality.review_items(records, inventory)[0])
    if change == "text":
        records[0]["examples"] = ["I love you."]
    elif change == "scope":
        records[0]["scope"] = "synset"
    elif change == "forms_scope":
        records[0]["irregular_forms_scope"] = "word"
    elif change == "definition":
        inventory[0]["definitions"] = ["have affection for"]
        records[0]["base_definition"] = "have affection for"
    else:
        inventory[0]["senses"][0][change] = "v" if change == "pos" else "beloved"
    with pytest.raises(ValueError, match="stale review content"):
        quality.validate_decisions(quality.review_items(records, inventory), [previous])


def test_rubric_change_invalidates_review(source, monkeypatch):
    records, inventory = source
    previous = decision(quality.review_items(records, inventory)[0])
    monkeypatch.setattr(quality, "RUBRIC", quality.RUBRIC + " Additional criterion.")
    with pytest.raises(ValueError, match="stale review content"):
        quality.validate_decisions(quality.review_items(records, inventory), [previous])


@pytest.mark.parametrize("field", ["word_id", "synset_id", "base_definition"])
def test_source_identity_must_match_review_context(source, field):
    records, inventory = source
    records[0][field] = "wrong"
    with pytest.raises(ValueError, match="source identity differs"):
        quality.review_items(records, inventory)


def test_removing_all_bad_fields_still_requires_review_of_the_correction(source):
    records, inventory = source
    records[0].pop("plain_language")
    records[0].pop("examples")
    assert quality.review_items(records, inventory) == []
    records[0]["requires_semantic_review"] = True
    items = quality.review_items(records, inventory)
    assert len(items) == 1
    with pytest.raises(ValueError, match="missing semantic reviews"):
        quality.validate_decisions(items, [])


def test_correction_inputs_require_exact_negative_reviews(source):
    spec = importlib.util.spec_from_file_location(
        "learner_corrections", ROOT / "prepare_corrections.py"
    )
    corrections = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corrections)
    records, inventory = source
    inventory[0]["frequency_rank"] = 1
    item = quality.review_items(records, inventory)[0]
    assert corrections.prepare(records, inventory, [decision(item)], []) == []
    result = corrections.prepare(records, inventory, [decision(item, "reject")], [])
    assert result[0]["correction"]["issues"][0]["field"] == "examples"
    records[0].update(reviewer="old-reviewer", review_status="ai-reviewed")
    revised = corrections.remove_flagged_fields(records, [decision(item, "reject")])
    assert "examples" not in revised[0]
    assert "reviewer" not in revised[0]
    assert revised[0]["requires_semantic_review"]
    assert revised[0]["plain_language"] == records[0]["plain_language"]
    assert records[0]["examples"] == ["Hello, my love."]
    assert (
        quality.review_items(revised, inventory)[0]["input_sha256"]
        != item["input_sha256"]
    )
    records[0]["examples"] = ["Different text."]
    with pytest.raises(ValueError, match="stale review content"):
        corrections.prepare(records, inventory, [decision(item, "reject")], [])


@pytest.mark.parametrize("verdict", ["reject", "uncertain"])
def test_negative_or_uncertain_review_blocks_release(source, verdict):
    items = quality.review_items(*source)
    with pytest.raises(ValueError, match="unresolved semantic review"):
        quality.validate_decisions(items, [decision(items[0], verdict)])


def test_duplicate_unknown_and_contradictory_decisions_are_rejected(source):
    items = quality.review_items(*source)
    row = decision(items[0])
    for rows, message in [
        ([row, row], "duplicate or unknown"),
        ([{**row, "sense_id": "wrong"}], "duplicate or unknown"),
        (
            [{**row, "issues": [{"field": "examples", "reason": "bad"}]}],
            "inconsistent review issues",
        ),
        ([{**row, "rationale": ""}], "missing review rationale"),
        ([{**row, "review_run": ""}], "missing review run"),
        ([{**row, "reviewer": "gpt-6-luna"}], "wrong reviewer"),
    ]:
        with pytest.raises(ValueError, match=message):
            quality.validate_decisions(items, rows)


def test_calibration_rejects_blanket_pass_blanket_reject_and_stale_cases():
    fixtures, controls = calibration()
    for rows in (
        [decision(i) for i in fixtures],
        [decision(i, "reject") for i in fixtures],
    ):
        with pytest.raises(ValueError, match="failed calibration"):
            quality.validate_calibration(fixtures, rows)
    altered = copy.deepcopy(fixtures)
    altered[0]["content"]["annotations"] = []
    with pytest.raises(ValueError, match="input hash does not match"):
        quality.validate_calibration(altered, controls)
    with pytest.raises(ValueError, match="incomplete calibration"):
        quality.validate_calibration([], [])


def test_calibration_is_required_for_each_reviewer_run(source):
    items = quality.review_items(*source)
    fixtures, controls = calibration("different-run")
    with pytest.raises(ValueError, match="missing semantic reviews"):
        quality.validate_release(*source, [decision(items[0])], fixtures, controls)


def test_native_exemption_only_accepts_verified_topic_links(source):
    _, inventory = source
    row = {
        "sense_id": "love-1-n",
        "word_id": "love-n",
        "synset_id": "1-n",
        "base_definition": "a beloved person",
        "creator": "WordNet",
        "source": "omw-en:1.4",
        "domains": ["relationships"],
        "domain_evidence": [{"label": "relationships", "synset_id": "topic-1-n"}],
    }
    assert quality.review_items([row], inventory) == []
    with pytest.raises(ValueError, match="cannot bypass review"):
        quality.review_items([{**row, "register": ["cakewalk"]}], inventory)
    with pytest.raises(ValueError, match="cannot bypass review"):
        quality.review_items([{**row, "examples": ["Bad example."]}], inventory)
    with pytest.raises(ValueError, match="unverified native topic"):
        quality.review_items([{**row, "domains": ["law"]}], inventory)


def test_known_failures_and_controls_remain_in_calibration():
    fixtures, _ = calibration()
    assert sum(i["expected_accept"] for i in fixtures) == 4
    rejected = [i["content"] for i in fixtures if not i["expected_accept"]]
    for sid in [
        "omw-en-run-00558883-n",
        "omw-en-medical-00142361-n",
        "omw-en-growth-13489037-n",
        "omw-en-replacement-13547925-n",
    ]:
        assert any(i["sense_id"] == sid for i in rejected)


def test_reviewer_calibration_input_hides_answers():
    fixtures, controls = calibration()
    inputs = [quality.blind_fixture(item) for item in fixtures]
    assert all("expected_accept" not in item for item in inputs)
    quality.validate_decisions(inputs, controls, require_accept=False)


def test_native_usage_examples_are_not_register_labels():
    spec = importlib.util.spec_from_file_location(
        "learner_candidates", ROOT / "prepare_candidates.py"
    )
    candidates = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidates)
    row = {}
    candidates.native_labels(
        {
            "relations": [
                {
                    "type": "exemplifies",
                    "forms": ["cakewalk"],
                    "target_synset_id": "term-1",
                },
                {
                    "type": "domain_topic",
                    "forms": ["biology"],
                    "target_synset_id": "topic-1",
                },
            ]
        },
        row,
    )
    assert row == {
        "domains": ["biology"],
        "domain_evidence": [{"label": "biology", "synset_id": "topic-1"}],
    }


@pytest.fixture
def package(source, tmp_path):
    import gzip
    import hashlib
    import lzma

    from wn import lmf

    spec = importlib.util.spec_from_file_location(
        "learner_check", ROOT / "check_release.py"
    )
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    records, inventory = source
    records[0].update(
        base_definition="a beloved person",
        status="unreviewed",
        reviewer="gpt-6-luna",
        review_status="ai-reviewed",
    )
    fixtures, controls = calibration()
    items = quality.review_items(records, inventory)
    reviews = [decision(items[0])]
    data = {
        "reviewed-records.jsonl.xz": records,
        "quality-reviews.jsonl.xz": reviews,
        "quality-context.jsonl.xz": quality.compact_inventory(inventory),
        "quality-calibration-decisions.jsonl": controls,
        "withheld.jsonl": [],
    }
    for name, rows in data.items():
        value = "".join(json.dumps(r) + "\n" for r in rows).encode()
        (tmp_path / name).write_bytes(
            lzma.compress(value) if name.endswith(".xz") else value
        )
    (tmp_path / "quality-calibration.json").write_text(json.dumps(fixtures))
    resource, counts = checker.builder.build_resource(
        checker.builder.mark_semantic_review(records),
        {"1-n": []},
        {"love-1-n"},
    )
    xml = tmp_path / "extension.xml"
    lmf.dump(resource, xml)
    compiled = gzip.compress(xml.read_bytes(), mtime=0)
    (tmp_path / "rylo-en-learner.xml.gz").write_bytes(compiled)
    manifest = {
        "inputs": {
            name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
            for name in [*data, "quality-calibration.json"]
        },
        "extension_sha256": hashlib.sha256(compiled).hexdigest(),
        "counts": counts,
        "withheld_senses": [],
        "quality_gate": quality.validate_release(
            records, inventory, reviews, fixtures, controls
        ),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return checker, tmp_path, manifest


def test_package_verifier_recompiles_approved_source(package):
    checker, path, _ = package
    assert checker.check_release(path)["status"] == "passed"


def test_updating_manifest_cannot_approve_changed_compiled_content(package):
    import gzip
    import hashlib

    checker, path, manifest = package
    target = path / "rylo-en-learner.xml.gz"
    xml = gzip.decompress(target.read_bytes()).replace(
        b"Hello, my love.", b"I love this."
    )
    target.write_bytes(gzip.compress(xml, mtime=0))
    manifest["extension_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="differs from approved source"):
        checker.check_release(path)


def test_source_change_needs_new_review_even_with_updated_manifest(package):
    import hashlib
    import lzma

    checker, path, manifest = package
    target = path / "reviewed-records.jsonl.xz"
    rows = quality.read_jsonl(target)
    rows[0]["examples"] = ["I love this."]
    target.write_bytes(
        lzma.compress("".join(json.dumps(r) + "\n" for r in rows).encode())
    )
    manifest["inputs"][target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="stale review content"):
        checker.check_release(path)


def test_quarantine_preserves_bad_source_and_never_publishes_partial_review(source):
    spec = importlib.util.spec_from_file_location(
        "learner_apply", ROOT / "apply_reviews.py"
    )
    apply = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(apply)
    records, inventory = source
    original = copy.deepcopy(records)
    item = quality.review_items(records, inventory)[0]
    fixtures, controls = calibration()
    with pytest.raises(ValueError, match="missing semantic reviews"):
        apply.select_reviewed(records, inventory, [], fixtures, controls, [])
    result = apply.select_reviewed(
        records, inventory, [decision(item, "reject")], fixtures, controls, []
    )
    assert result["accepted"] == []
    assert result["quarantined"] == original
    assert result["reviews"] == []
    assert result["withheld"][0]["sense_id"] == "love-1-n"
    assert "Target is used as a verb" in result["withheld"][0]["reason"]
    assert records == original
    revised = [{**records[0], "requires_semantic_review": True, "author_run": "author"}]
    item = quality.review_items(revised, inventory)[0]
    approved = apply.select_reviewed(
        revised, inventory, [decision(item)], fixtures, controls, []
    )["accepted"][0]
    assert approved["reviewer"] == quality.REVIEWER
    assert approved["review_status"] == "ai-reviewed"
    assert "reviewer" not in revised[0]


@pytest.mark.parametrize("author", [None, "", " ", 123])
def test_authored_correction_requires_author_identity(source, author):
    records, inventory = source
    records[0].update(requires_semantic_review=True, author_run=author)
    with pytest.raises(ValueError, match="requires author_run"):
        quality.review_items(records, inventory)


def test_new_generator_requires_author_even_for_empty_output(source):
    records, inventory = source
    records[0].pop("examples")
    records[0].pop("plain_language")
    records[0]["prompt_version"] = "english-learner-7"
    with pytest.raises(ValueError, match="requires author_run"):
        quality.review_items(records, inventory)
