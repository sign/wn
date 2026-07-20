import pytest
from starlette.testclient import TestClient

import wn
import wn._db
from wn import web

# clearing connections on teardown (see conftest.py) isn't enough. For
# this we apparently need to monkeypatch the wn._db.pool as well.

@pytest.fixture
def mini_db_web(monkeypatch, mini_db_dir):
    with monkeypatch.context() as m:
        m.setattr(wn._db, 'pool', {})
        m.setattr(wn.config, 'data_directory', mini_db_dir)
        m.setattr(wn.config, 'allow_multithreading', True)
        yield
        wn._db.clear_connections()


client = TestClient(web.app)


@pytest.mark.usefixtures('mini_db_web')
def test_root():
    response = client.get('/')
    assert response.status_code == 200
    data = response.json()
    assert 'endpoints' in data


@pytest.mark.usefixtures('mini_db_web')
def test_lexicons():
    response = client.get("/lexicons")
    assert response.status_code == 200
    data = response.json()["data"]
    assert [lex["id"] for lex in data] == ["test-en:1", "test-es:1"]


@pytest.mark.usefixtures('mini_db_web')
def test_words():
    response = client.get("/words")
    assert response.status_code == 200
    data = response.json()["data"]
    word_ids = {word["id"] for word in data}
    assert "test-en-information-n" in word_ids
    assert "test-es-información-n" in word_ids

    response = client.get("/words", params={"lexicon": "test-en:1"})
    assert response.status_code == 200
    data = response.json()["data"]
    word_ids = {word["id"] for word in data}
    assert "test-en-information-n" in word_ids
    assert "test-es-información-n" not in word_ids


@pytest.mark.usefixtures('mini_db_web')
def test_senses():
    response = client.get("/senses")
    assert response.status_code == 200
    data = response.json()["data"]
    sense_ids = {sense["id"] for sense in data}
    assert "test-en-information-n-0001-01" in sense_ids
    assert "test-es-información-n-0001-01" in sense_ids

    response = client.get("/senses", params={"lexicon": "test-en:1"})
    assert response.status_code == 200
    data = response.json()["data"]
    sense_ids = {sense["id"] for sense in data}
    assert "test-en-information-n-0001-01" in sense_ids
    assert "test-es-información-n-0001-01" not in sense_ids


@pytest.mark.usefixtures('mini_db_web')
def test_synsets():
    response = client.get("/synsets")
    assert response.status_code == 200
    data = response.json()["data"]
    synset_ids = {synset["id"] for synset in data}
    assert "test-en-0001-n" in synset_ids
    assert "test-es-0001-n" in synset_ids

    response = client.get("/synsets", params={"lexicon": "test-en:1"})
    assert response.status_code == 200
    data = response.json()["data"]
    synset_ids = {synset["id"] for synset in data}
    assert "test-en-0001-n" in synset_ids
    assert "test-es-0001-n" not in synset_ids


@pytest.mark.usefixtures('mini_db_web')
def test_words_included_synset_enrichment():
    response = client.get(
        "/lexicons/test-en:1/words", params={"form": "random sample"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1
    included = data[0]["included"]
    attrs = next(
        ss["attributes"] for ss in included if ss["id"] == "test-en-0005-n"
    )
    assert attrs["members"] == ["random sample"]
    # breadcrumb lemmas are ordered root -> immediate hypernym
    assert attrs["hypernyms"] == ["information", "example", "sample"]
    # the mini fixture has no similar/also relations
    assert "see_also" not in attrs

    # synset with multiple members exposes them all
    response = client.get(
        "/lexicons/test-en:1/words", params={"form": "example"}
    )
    attrs = response.json()["data"][0]["included"][0]["attributes"]
    assert set(attrs["members"]) == {"example", "illustration"}


@pytest.mark.usefixtures('mini_db_web')
def test_lexicon_words():
    response1 = client.get("/lexicons/test-en:1/words")
    response2 = client.get("/words", params={"lexicon": "test-en:1"})
    assert response1.status_code == 200
    assert response2.status_code == 200
    data1 = response1.json()["data"]
    data2 = response2.json()["data"]
    assert {word["id"] for word in data1} == {word["id"] for word in data2}


@pytest.mark.usefixtures('mini_db_web')
def test_lexicon_senses():
    response1 = client.get("/lexicons/test-en:1/senses")
    response2 = client.get("/senses", params={"lexicon": "test-en:1"})
    assert response1.status_code == 200
    assert response2.status_code == 200
    data1 = response1.json()["data"]
    data2 = response2.json()["data"]
    assert {sense["id"] for sense in data1} == {sense["id"] for sense in data2}


@pytest.mark.usefixtures('mini_db_web')
def test_lexicon_synsets():
    response1 = client.get("/lexicons/test-en:1/synsets")
    response2 = client.get("/synsets", params={"lexicon": "test-en:1"})
    assert response1.status_code == 200
    assert response2.status_code == 200
    data1 = response1.json()["data"]
    data2 = response2.json()["data"]
    assert {synset["id"] for synset in data1} == {synset["id"] for synset in data2}


@pytest.mark.usefixtures('mini_db_web')
def test_forms():
    response = client.get("/lexicons/test-en:1/forms")
    assert response.status_code == 200
    body = response.json()
    assert "information" in body["data"]
    assert "data" in body["data"]  # secondary written form of "datum"
    assert body["meta"]["total"] == len(body["data"])


@pytest.mark.usefixtures('mini_db_web')
def test_forms_for_synsets():
    response = client.post(
        "/lexicons/test-en:1/forms",
        json={"synsets": ["test-en-0001-n", "test-en-0006-n"]},
    )
    assert response.status_code == 200
    body = response.json()
    # "information" expresses 0001; "datum" and its secondary written form
    # "data" both express 0006.
    assert sorted(body["data"]) == ["data", "datum", "information"]
    assert body["meta"]["total"] == 3


@pytest.mark.usefixtures('mini_db_web')
def test_forms_for_synsets_include_synsets():
    response = client.post(
        "/lexicons/test-en:1/forms",
        json={"synsets": ["test-en-0001-n", "test-en-0006-n"], "include_synsets": True},
    )
    assert response.status_code == 200
    body = response.json()
    # Each matched form carries the synset ids it expresses, so consumers can
    # derive per-form freshness from per-synset timestamps (SIGN-640).
    assert body["data"] == {
        "information": ["test-en-0001-n"],
        "datum": ["test-en-0006-n"],
        "data": ["test-en-0006-n"],
    }
    assert body["meta"]["total"] == 3


@pytest.mark.usefixtures('mini_db_web')
def test_forms_for_synsets_empty_and_unknown_ids():
    response = client.post("/lexicons/test-en:1/forms", json={"synsets": []})
    assert response.status_code == 200
    assert response.json()["data"] == []

    response = client.post(
        "/lexicons/test-en:1/forms", json={"synsets": ["no-such-synset-n"]}
    )
    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.usefixtures('mini_db_web')
def test_forms_for_synsets_rejects_non_string_ids():
    response = client.post("/lexicons/test-en:1/forms", json={"synsets": [1]})
    assert response.status_code == 400


@pytest.mark.usefixtures('mini_db_web')
def test_forms_for_synsets_rejects_malformed_bodies():
    response = client.post(
        "/lexicons/test-en:1/forms",
        content=b"not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400

    response = client.post("/lexicons/test-en:1/forms", json=["test-en-0001-n"])
    assert response.status_code == 400


@pytest.mark.usefixtures('mini_db_web')
def test_forms_for_synsets_bad_lexicon_specifier():
    response = client.post(
        "/lexicons/test-en/forms", json={"synsets": ["test-en-0001-n"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0
