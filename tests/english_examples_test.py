import importlib.util
import json
from pathlib import Path

import pytest

import wn

DATA_DIR = Path(__file__).resolve().parents[1] / "extensions" / "english-examples"
spec = importlib.util.spec_from_file_location(
    "english_examples", DATA_DIR / "enrich.py"
)
enrichment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enrichment)


@pytest.fixture
def example_db(monkeypatch, tmp_path, datadir):
    monkeypatch.setattr(wn.config, "data_directory", tmp_path / "db")
    wn.add(datadir / "mini-lmf-1.0.xml", progress_handler=None)
    yield
    wn._db.clear_connections()


@pytest.fixture
def example_file(tmp_path):
    path = tmp_path / "examples.json"
    path.write_text(json.dumps([{
        "word": "information",
        "sense": "test-en-information-n-0001-01",
        "example": "The guide contains useful information.",
    }]), encoding="utf-8")
    return path


@pytest.mark.usefixtures("example_db")
def test_examples_preserve_existing_data_and_are_idempotent(example_file):
    sense = wn.sense("test-en-information-n-0001-01")
    previous = sense.synset().examples()
    enrichment.add_examples(example_file, "test-en:1")
    enrichment.add_examples(example_file, "test-en:1")
    text = "The guide contains useful information."
    assert sense.examples().count(text) == 1
    assert sense.synset().examples() == [*previous, text]
    metadata = sense.examples(data=True)[0].metadata()
    assert metadata["identifier"] == sense.id
    assert metadata["creator"] == "OpenAI Codex"
    assert metadata["status"] == "unreviewed"

    # Newer API versions must preserve attribution and source-sense scoping.
    from wn.web import _word_examples

    args = (sense.synset(), sense.word())
    visible, details = _word_examples(*args, {sense.id}, ["information"], True)
    assert text in visible
    assert {"text": text, "metadata": metadata} in details
    visible, _ = _word_examples(*args, set(), ["information"], True)
    assert text not in visible

    ranked = example_file.with_suffix(".tsv")
    ranked.write_text("word\tcount\tsource_rank\ninformation\t10\t1\n")
    assert enrichment.check_coverage(ranked, "test-en:1") == 1
    ranked.write_text("word\tcount\tsource_rank\nmissing\t10\t1\n")
    with pytest.raises(ValueError, match="Words without examples: missing"):
        enrichment.check_coverage(ranked, "test-en:1")


@pytest.mark.usefixtures("example_db")
@pytest.mark.parametrize("bad_record", [
    {"word": "information", "sense": "nonexistent", "example": "More information."},
    {"word": "example", "sense": "test-en-information-n-0001-01",
     "example": "Here is an example."},
    {"word": "information", "sense": "test-en-information-n-0001-01",
     "example": "An informational booklet."},
])
def test_invalid_target_or_word_does_not_partially_import(example_file, bad_record):
    records = json.loads(example_file.read_text())
    records.append(bad_record)
    example_file.write_text(json.dumps(records))
    sense = wn.sense("test-en-information-n-0001-01")
    previous = sense.synset().examples()
    with pytest.raises(ValueError, match=r"Missing sense/form|must be a sentence"):
        enrichment.add_examples(example_file, "test-en:1")
    assert sense.examples() == []
    assert sense.synset().examples() == previous


def test_curated_examples_and_ranking():
    records = json.loads((DATA_DIR / "examples.json").read_text())
    rows = (DATA_DIR / "top1000.tsv").read_text().splitlines()[1:]
    words = [row.split("\t")[0] for row in rows]
    assert len(words) == len(set(words)) == 1000
    counts = [int(row.split("\t")[1]) for row in rows]
    assert counts == sorted(counts, reverse=True)
    assert len({(r["sense"], r["example"]) for r in records}) == len(records)
    for record in records:
        assert record["word"].lower() in words
        assert record["example"].endswith((".", "!", "?"))
        assert enrichment.contains_word(record["example"], record["word"])
    assert {r["sense"] for r in records if r["word"] == "to"} == {
        "L1327670-S1", "L2985-S1", "L248738-S1", "L248738-S2",
        "L248738-S3", "L1327669-S1",
    }
