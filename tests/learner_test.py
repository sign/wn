import json

import pytest
from starlette.testclient import TestClient

import wn
from wn import lmf, web
from wn.learner import ANNOTATION_TYPE, validate_learner_fields

SYNSET = "test-en-0001-n"
WORD = "test-en-information-n"
SENSE = "test-en-information-n-0001-01"


def annotation(scope, text="something that informs", **fields):
    definition = {
        "text": text,
        "meta": {
            "type": ANNOTATION_TYPE,
            "description": json.dumps({"schema_version": 1, "scope": scope, **fields}),
            "creator": "test-model",
            "source": "test-generation",
            "status": "unreviewed",
        },
    }
    if scope == "sense":
        definition["sourceSense"] = SENSE
    return definition


def resource(definitions=None):
    return {
        "lmf_version": "1.1",
        "lexicons": [
            {
                "id": "test-learner",
                "version": "1",
                "label": "Learner notes",
                "language": "en",
                "email": "test@example.com",
                "license": "test",
                "extends": {"id": "test-en", "version": "1"},
                "entries": [
                    {
                        "external": True,
                        "id": WORD,
                        "senses": [{"external": True, "id": SENSE}],
                    }
                ],
                "synsets": [
                    {
                        "external": True,
                        "id": SYNSET,
                        "definitions": definitions
                        if definitions is not None
                        else [
                            annotation("synset", domains=["computing"]),
                            annotation(
                                "sense",
                                "Facts that tell you something.",
                                grammar_notes=["Usually uncountable."],
                            ),
                            annotation(
                                "word",
                                word_id=WORD,
                                usage_tips=["Ask for information."],
                            ),
                        ],
                        "examples": [
                            {
                                "text": "The guide gave us useful information.",
                                "meta": {
                                    "creator": "test-model",
                                    "status": "unreviewed",
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }


@pytest.fixture
def learner_db(monkeypatch, tmp_path, datadir):
    with monkeypatch.context() as m:
        m.setattr(wn.config, "data_directory", tmp_path / "database")
        m.setattr(wn.config, "allow_multithreading", True)
        m.setattr(wn._db, "pool", {})
        wn.add(datadir / "mini-lmf-1.0.xml", progress_handler=None)
        yield
        wn._db.clear_connections()


@pytest.mark.usefixtures("learner_db")
def test_native_extension_roundtrip_and_removal(tmp_path):
    base = wn.Wordnet("test-en:1")
    synset = base.synset(SYNSET)
    original_examples = synset.examples()
    original_counts = (len(base.words()), len(base.synsets()), len(base.senses()))
    path = tmp_path / "learner.xml"
    lmf.dump(resource(), path)
    wn.add(path, progress_handler=None)

    assert synset.definition() == "something that informs"
    assert synset.definitions() == ["something that informs"]
    assert [definition.text for definition in synset.definitions(data=True)] == [
        "something that informs"
    ]
    assert synset.examples() == [
        *original_examples,
        "The guide gave us useful information.",
    ]
    assert len(synset.learner_data()) == 3
    assert "plain_language" not in synset.learner_data()[0]
    notes = base.sense(SENSE).learner_data()
    assert len(notes) == 2
    assert notes[1]["plain_language"] == "Facts that tell you something."
    assert notes[1]["source_sense_id"] == SENSE
    assert notes[1]["metadata"]["creator"] == "test-model"
    assert notes[1]["metadata"]["status"] == "unreviewed"
    assert base.word(WORD).learner_data()[0]["usage_tips"] == ["Ask for information."]
    assert original_counts == (
        len(base.words()),
        len(base.synsets()),
        len(base.senses()),
    )
    assert wn.synset(SYNSET).learner_data() == synset.learner_data()

    exported = tmp_path / "export.xml"
    wn.export(wn.lexicons(lexicon="test-learner:1"), exported, version="1.1")
    wn.remove("test-learner:1")
    assert synset.learner_data() == []
    assert synset.examples() == original_examples
    assert synset.definition() == "something that informs"
    wn.add(exported, progress_handler=None)
    assert base.sense(SENSE).learner_data() == notes


@pytest.mark.usefixtures("learner_db")
def test_web_exposes_learner_notes_for_explicit_base(tmp_path):
    path = tmp_path / "learner.xml"
    lmf.dump(resource(), path)
    wn.add(path, progress_handler=None)
    client = TestClient(web.app)
    response = client.get(f"/lexicons/test-en:1/synsets/{SYNSET}")
    assert response.status_code == 200
    attrs = response.json()["data"]["attributes"]
    assert attrs["definition"] == "something that informs"
    assert len(attrs["learner_data"]) == 3
    assert "The guide gave us useful information." in attrs["examples"]


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"schema_version": True, "scope": "synset"},
        {"schema_version": 2, "scope": "synset"},
        {"schema_version": 1, "scope": "unknown"},
        {"schema_version": 1, "scope": "word"},
        {"schema_version": 1, "scope": "synset", "irregular_forms": {}},
        {"schema_version": 1, "scope": "sense", "domains": "medical"},
        {"schema_version": 1, "scope": "sense", "domains": [""]},
        {"schema_version": 1, "scope": "sense", "typo": []},
    ],
)
def test_reject_invalid_fields(fields):
    with pytest.raises(wn.Error):
        validate_learner_fields(fields)


def test_irregular_forms_are_word_scoped():
    fields = {
        "schema_version": 1,
        "scope": "word",
        "word_id": "test-child-n",
        "irregular_forms": {"plural": ["children"]},
    }
    assert validate_learner_fields(fields) == fields


def test_irregular_forms_can_be_sense_specific():
    fields = {
        "schema_version": 1,
        "scope": "sense",
        "irregular_forms": {"past": ["lay"], "past_participle": ["lain"]},
    }
    assert validate_learner_fields(fields) == fields


@pytest.mark.usefixtures("learner_db")
def test_sense_notes_do_not_leak_to_synonyms(tmp_path):
    entry = resource()
    lexicon = entry["lexicons"][0]
    lexicon["entries"][0]["id"] = "test-en-example-n"
    sense = "test-en-example-n-0002-01"
    lexicon["entries"][0]["senses"][0]["id"] = sense
    note = annotation("sense", usage_tips=["An example of something."])
    note["sourceSense"] = sense
    lexicon["synsets"][0]["id"] = "test-en-0002-n"
    lexicon["synsets"][0]["definitions"] = [note]
    path = tmp_path / "sense.xml"
    lmf.dump(entry, path)
    wn.add(path, progress_handler=None)
    base = wn.Wordnet("test-en:1")
    assert len(base.sense(sense).learner_data()) == 1
    assert base.sense("test-en-illustration-n-0002-01").learner_data() == []
    client = TestClient(web.app)
    for word, expected in [("example", 1), ("illustration", 0)]:
        response = client.get("/lexicons/test-en:1/words", params={"form": word})
        notes = response.json()["data"][0]["included"][0]["attributes"]["learner_data"]
        assert len(notes) == expected


@pytest.mark.usefixtures("learner_db")
def test_reject_invalid_import_without_leaving_extension(tmp_path):
    invalid = annotation("sense", grammar_notes=["Use as a noun."])
    invalid["meta"]["description"] = "not json"
    path = tmp_path / "invalid.xml"
    lmf.dump(resource([invalid]), path)
    with pytest.raises(wn.Error, match="invalid learner annotation JSON"):
        wn.add(path, progress_handler=None)
    assert wn.lexicons(lexicon="test-learner:1") == []
    assert wn.synset(SYNSET).definition() == "something that informs"


@pytest.mark.usefixtures("learner_db")
@pytest.mark.parametrize(
    ("scope", "target"),
    [
        ("sense", "test-en-example-n-0002-01"),
        ("sense", "missing-sense"),
        ("word", "test-en-example-n"),
        ("word", "missing-word"),
    ],
)
def test_reject_annotation_target_outside_concept(tmp_path, scope, target):
    item = annotation(scope)
    if scope == "sense":
        item["sourceSense"] = target
    else:
        item = annotation(scope, word_id=target)
    path = tmp_path / "wrong-target.xml"
    lmf.dump(resource([item]), path)
    with pytest.raises(wn.Error, match="target is not a member"):
        wn.add(path, progress_handler=None)
    assert wn.lexicons(lexicon="test-learner:1") == []


@pytest.mark.usefixtures("learner_db")
def test_web_keeps_generated_examples_on_their_exact_sense(tmp_path):
    entry = resource()
    lexicon = entry["lexicons"][0]
    lexicon["entries"] = []
    example_text = "The teacher wrote an example on the board."
    illustration_text = "The speaker offered an illustration of the problem."
    lexicon["synsets"] = [
        {
            "id": "test-en-0002-n",
            "external": True,
            "examples": [
                {
                    "text": text,
                    "meta": {
                        "type": "learner-example",
                        "identifier": sense,
                        "creator": "test-model",
                        "status": "unreviewed",
                    },
                }
                for sense, text in [
                    ("test-en-example-n-0002-01", example_text),
                    ("test-en-illustration-n-0002-01", illustration_text),
                ]
            ],
        }
    ]
    path = tmp_path / "scoped-examples.xml"
    lmf.dump(entry, path)
    wn.add(path, progress_handler=None)
    client = TestClient(web.app)
    for word, own, other in [
        ("example", example_text, illustration_text),
        ("illustration", illustration_text, example_text),
    ]:
        response = client.get("/lexicons/test-en:1/words", params={"form": word})
        assert response.status_code == 200
        attributes = response.json()["data"][0]["included"][0]["attributes"]
        examples = attributes["examples"]
        assert [item["text"] for item in attributes["example_details"]] == [own]
        assert attributes["example_details"][0]["metadata"]["creator"] == "test-model"
        assert own in examples
        assert other not in examples
        assert len(examples) == 3  # two original examples plus this sense's example
        assert f"we need an {word} here" in examples  # legacy personalization remains
    concept_examples = wn.Wordnet("test-en:1").synset("test-en-0002-n").examples()
    assert example_text in concept_examples
    assert illustration_text in concept_examples
