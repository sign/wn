"""Generator safeguards must reject malformed or mis-targeted enrichment."""

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[1] / "extensions/english-learner/generation.py"
_SPEC = importlib.util.spec_from_file_location("learner_generation", _PATH)
generator = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(generator)


@pytest.fixture
def row():
    return {
        "word": "love",
        "examples": [],
        "senses": [{"matching_forms": ["love"]}],
    }


def test_missing_examples_required(row):
    with pytest.raises(ValueError, match="requires two"):
        generator.validate({"id": 0, "enrichment": {}}, row, 0)


def test_original_examples_are_preserved(row):
    row["examples"] = ["You are my love."]
    generator.validate({"id": 0, "enrichment": {}}, row, 0)
    with pytest.raises(ValueError, match="already has examples"):
        generator.validate(
            {
                "id": 0,
                "enrichment": {"examples": ["Hello, my love.", "My love is waiting."]},
            },
            row,
            0,
        )


def test_example_must_contain_exact_word(row):
    item = {
        "id": 0,
        "enrichment": {"examples": ["Hello, my love.", "My beloved is waiting."]},
    }
    with pytest.raises(ValueError, match="exact matching form"):
        generator.validate(item, row, 0)


def test_capitalized_abbreviation_is_not_common_word(row):
    row["senses"][0]["matching_forms"] = ["IT"]
    with pytest.raises(ValueError, match="exact matching form"):
        generator.validate(
            {"id": 0, "enrichment": {"examples": ["It is expensive.", "We need it."]}},
            row,
            0,
        )


def test_regular_inflections_keep_the_required_part_of_speech(row):
    row.update(pos="v", senses=[{"matching_forms": ["thank"]}])
    generator.validate_examples(
        ["She thanked the driver.", "He was thanking his hosts."], row
    )
    row.update(pos="n", senses=[{"matching_forms": ["review"]}])
    with pytest.raises(ValueError, match="exact matching form"):
        generator.validate_examples(
            ["The court reviewed the case.", "They reviewed the contract."], row
        )


def test_order_and_allowed_fields(row):
    row["examples"] = ["You are my love."]
    with pytest.raises(ValueError, match="input order"):
        generator.validate({"id": 1, "enrichment": {}}, row, 0)
    with pytest.raises(ValueError, match="Invalid enrichment"):
        generator.validate({"id": 0, "enrichment": {"invented": "field"}}, row, 0)


def test_input_hash_is_order_independent_and_changes_with_input(row):
    assert generator.input_hash(row) == generator.input_hash(
        dict(reversed(list(row.items())))
    )
    changed = {**row, "word": "honey"}
    assert generator.input_hash(row) != generator.input_hash(changed)


def test_expand_inventory_keeps_exact_senses_distinct():
    sense = {"sense_id": "lower-i", "lemma": "i", "matching_forms": ["i"]}
    upper = {"sense_id": "upper-I", "lemma": "I", "matching_forms": ["I"]}
    inputs = [
        {"frequency_rank": 20, "senses": [sense]},
        {"frequency_rank": 10, "senses": [upper, sense]},
    ]
    output = generator.expand_inventory(inputs)
    assert len(output) == 2
    assert all(r["frequency_rank"] == 10 for r in output)
    assert output[0]["senses"][0]["lemma"] == "I"
    assert output[1]["senses"][0]["lemma"] == "i"


def test_failed_batch_retries_each_sense_independently(monkeypatch):
    rows = [
        {"word": "good", "senses": [{"sense_id": "good"}]},
        {"word": "bad", "senses": [{"sense_id": "bad"}]},
    ]

    def fake_generate(batch, args, error_hint=None):
        if len(batch) > 1 or batch[0]["word"] == "bad":
            raise ValueError("rejected")
        return [{"enrichment": {}}], {}

    monkeypatch.setattr(generator, "generate", fake_generate)
    monkeypatch.setattr(generator, "output_record", lambda row, item, args: row)
    records, errors = generator.process_batch(rows, None)
    assert [r["word"] for r in records] == ["good"]
    assert [r["sense_id"] for r in errors] == ["bad"]


def test_known_noun_plurals_and_symbol_case():
    rows = []
    for i, word in enumerate(["have", "person", "Na"]):
        rows.append(
            {
                "frequency_rank": i,
                "pos": "n",
                "definitions": [word],
                "senses": [{"sense_id": word, "lemma": word, "matching_forms": [word]}],
            }
        )
    result = generator.expand_inventory(rows)
    assert "haves" in result[0]["senses"][0]["matching_forms"]
    assert "people" in result[1]["senses"][0]["matching_forms"]
    assert result[2]["senses"][0]["matching_forms"] == ["Na"]


def test_response_type_and_duplicate_examples(row):
    with pytest.raises(ValueError, match="must be an object"):
        generator.validate([], row, 0)
    with pytest.raises(ValueError, match="Duplicate examples"):
        generator.validate(
            {
                "id": 0,
                "enrichment": {"examples": ["Hello, my love.", "Hello, my love."]},
            },
            row,
            0,
        )
    with pytest.raises(ValueError, match="Server response"):
        generator.normalize_response([], "openai")
    with pytest.raises(ValueError, match="Server choices"):
        generator.normalize_response({"choices": []}, "openai")


def test_prompt_distractors_are_not_exported():
    entries = [
        {
            "word": "bank",
            "frequency_rank": 1,
            "pos": "n",
            "definitions": [definition],
            "senses": [
                {"sense_id": str(i), "lemma": "bank", "matching_forms": ["bank"]}
            ],
        }
        for i, definition in enumerate(["financial institution", "sloping land"])
    ]
    output = generator.expand_inventory(entries)
    assert output[0]["other_meanings"] == [{"pos": "n", "definition": "sloping land"}]
    assert output[1]["other_meanings"] == [
        {"pos": "n", "definition": "financial institution"}
    ]


def test_lowercase_word_allows_sentence_initial_capitalization(row):
    generator.validate(
        {
            "id": 0,
            "enrichment": {
                "examples": [
                    "Love, please come and sit beside me.",
                    "Good morning, my love.",
                ]
            },
        },
        row,
        0,
    )


def test_prompt_word_preserves_exact_lemma_case():
    row = {
        "word": "in",
        "pos": "n",
        "definitions": ["a metallic element"],
        "examples": [],
        "relations": [],
        "senses": [
            {
                "lemma": "In",
                "matching_forms": ["In"],
                "forms": [],
                "tags": [],
                "syntactic_frames": [],
            }
        ],
    }
    assert generator.compact(row, 0)["word"] == "In"


def test_malformed_openai_usage_is_rejected():
    with pytest.raises(ValueError, match="Server usage"):
        generator.normalize_response(
            {
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": [1],
            },
            "openai",
        )
