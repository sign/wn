"""The release builder must preserve concepts and fail on incomplete coverage."""

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[1] / "extensions/english-learner/build_extension.py"
_SPEC = importlib.util.spec_from_file_location("learner_build", _PATH)
builder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(builder)


@pytest.fixture
def row():
    return {
        "word_id": "test-en-love-n",
        "sense_id": "test-en-love-1",
        "synset_id": "test-en-1-n",
        "base_definition": "a beloved person",
        "examples": ["Hello, my love.", "My love is waiting outside."],
        "plain_language": "Someone you love dearly.",
        "grammar_notes": ["Often used with a possessive: my love."],
        "creator": "test-model",
        "source": "test-source",
        "status": "unreviewed",
    }


def test_build_adds_only_external_identities_and_deduplicates(row):
    resource, counts = builder.build_resource([row, row], {row["synset_id"]: []})
    lexicon = resource["lexicons"][0]
    assert lexicon["extends"] == {"id": "omw-en", "version": "1.4"}
    assert all(e["external"] for e in lexicon["entries"])
    assert all(s["external"] for e in lexicon["entries"] for s in e["senses"])
    assert all(s["external"] for s in lexicon["synsets"])
    assert counts["examples"] == 2
    assert counts["annotations"] == 2
    assert counts["new_synsets"] == 0
    assert len(lexicon["synsets"][0]["examples"]) == 2
    assert len(lexicon["entries"][0]["senses"][0]["examples"]) == 2


def test_build_never_adds_examples_to_covered_concept(row):
    resource, counts = builder.build_resource([row], {row["synset_id"]: ["original"]})
    assert counts.get("examples", 0) == 0
    assert resource["lexicons"][0]["synsets"][0]["examples"] == []


def test_build_rejects_incomplete_coverage(row):
    with pytest.raises(ValueError, match="still lack examples"):
        builder.build_resource([row], {row["synset_id"]: [], "test-en-2-n": []})


def test_build_rejects_unknown_concept_and_conflicting_sense(row):
    with pytest.raises(ValueError, match="outside frequency inventory"):
        builder.build_resource([row], {})
    conflicting = {**row, "word_id": "test-en-wrong-word-n"}
    with pytest.raises(ValueError, match="conflicting sense identity"):
        builder.build_resource([row, conflicting], {row["synset_id"]: []})


def test_build_preserves_field_specific_provenance(row):
    row.update(
        plain_language_source="definitions-source", example_source="examples-source"
    )
    resource, _ = builder.build_resource([row], {row["synset_id"]: []})
    synset = resource["lexicons"][0]["synsets"][0]
    assert synset["definitions"][0]["meta"]["source"] == "definitions-source"
    assert synset["definitions"][1]["meta"]["source"] == "test-source"
    assert synset["examples"][0]["meta"]["source"] == "examples-source"


def test_build_requires_examples_for_each_target_sense(row):
    synonym = {
        **row,
        "word_id": "test-en-beloved-n",
        "sense_id": "test-en-beloved-1",
        "examples": [],
    }
    with pytest.raises(ValueError, match="target senses still lack examples"):
        builder.build_resource(
            [row, synonym],
            {row["synset_id"]: []},
            {row["sense_id"], synonym["sense_id"]},
        )


def test_build_rejects_known_unresolved_content(row):
    row["unresolved_reason"] = "The examples use the wrong part of speech."
    with pytest.raises(ValueError, match="unresolved content"):
        builder.build_resource([row], {row["synset_id"]: []})


def test_release_requires_review_but_native_labels_keep_their_source(row):
    with pytest.raises(ValueError, match="missing independent AI review"):
        builder.validate_review([row])
    reviewed = {**row, "reviewer": "review-model", "review_status": "ai-reviewed"}
    native = {**row, "creator": "WordNet", "source": "omw-en:1.4"}
    native["sense_id"] = "test-en-native-only"
    assert builder.validate_review([reviewed, native]) == {row["sense_id"]}
    # Reviewing a straightforward sense need not add any learner fields.
    empty = {key: value for key, value in reviewed.items()
             if key not in ("examples", "plain_language", "grammar_notes")}
    assert builder.validate_review([empty]) == {row["sense_id"]}


def test_explicitly_withheld_concept_is_not_counted_as_covered(row):
    original = {row["synset_id"]: [], "test-en-unresolved-n": []}
    resource, counts = builder.build_resource(
        [row], original, {row["sense_id"]}, {"test-en-unresolved-n"}
    )
    assert counts["concepts_with_added_examples"] == 1
    assert [s["id"] for s in resource["lexicons"][0]["synsets"]] == [row["synset_id"]]


def test_sense_specific_irregular_forms_do_not_conflict(row):
    first = {**row, "irregular_forms": {"past": ["lay"]}}
    second = {
        **row,
        "sense_id": "test-en-love-2",
        "irregular_forms": {"past": ["lied"]},
    }
    resource, counts = builder.build_resource([first, second], {row["synset_id"]: []})
    assert counts["irregular_forms"] == 2
    definitions = resource["lexicons"][0]["synsets"][0]["definitions"]
    import json

    forms = {
        d["sourceSense"]: json.loads(d["meta"]["description"])["irregular_forms"]
        for d in definitions
        if "irregular_forms" in json.loads(d["meta"]["description"])
    }
    assert forms == {
        first["sense_id"]: {"past": ["lay"]},
        second["sense_id"]: {"past": ["lied"]},
    }
