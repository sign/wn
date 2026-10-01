"""Typed learner annotations carried by ordinary WN-LMF definitions.

An additive definition with ``dc:type="learner-enrichment"`` carries a
plain-language explanation as its text and a versioned JSON object in
``dc:description``. Native metadata records provenance and review status.
This uses standard extension import/export and removal, without new entities.
"""

import json
from typing import Literal, TypedDict, cast

from wn._exceptions import Error
from wn._metadata import Metadata

ANNOTATION_TYPE = "learner-enrichment"


class LearnerFields(TypedDict, total=False):
    schema_version: Literal[1]
    scope: Literal["word", "sense", "synset"]
    word_id: str
    domains: list[str]
    register: list[str]
    usage: list[str]
    grammar_notes: list[str]
    irregular_forms: dict[str, list[str]]
    usage_tips: list[str]


class LearnerData(LearnerFields, total=False):
    plain_language: str
    source_sense_id: str
    lexicon: str
    metadata: Metadata


_LIST_FIELDS = {"domains", "register", "usage", "grammar_notes", "usage_tips"}
_FIELDS = _LIST_FIELDS | {"schema_version", "scope", "word_id", "irregular_forms"}


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    )


def _validate_irregular_forms(forms: object, scope: str) -> None:
    if scope == "synset":
        raise Error("irregular_forms require word or sense scope")
    if not isinstance(forms, dict) or not all(
        isinstance(key, str) and key.strip() and _strings(forms[key]) for key in forms
    ):
        raise Error("invalid learner annotation irregular_forms")


def validate_learner_fields(value: object) -> LearnerFields:
    """Validate a version-1 annotation, rejecting misspelled or mistyped fields.

    Empty optional fields should be omitted by producers. Irregular forms
    may be sense-specific (lie/lay versus lie/lied), but never concept-wide.
    """
    if not isinstance(value, dict) or value.keys() - _FIELDS:
        raise Error("invalid learner annotation fields")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise Error("unsupported learner annotation schema_version")
    scope = value.get("scope")
    if scope not in ("word", "sense", "synset"):
        raise Error("invalid learner annotation scope")
    if scope == "word":
        if not isinstance(value.get("word_id"), str) or not value["word_id"].strip():
            raise Error("word learner annotation requires word_id")
    elif "word_id" in value:
        raise Error("word_id requires word scope")
    for key in _LIST_FIELDS & value.keys():
        if not _strings(value[key]):
            raise Error(f"learner annotation {key} must be a list of strings")
    if "irregular_forms" in value:
        _validate_irregular_forms(value["irregular_forms"], scope)
    return cast("LearnerFields", value)


def decode_learner_data(
    text: str,
    source_sense_id: str | None,
    lexicon: str,
    metadata: Metadata,
    original_definitions: set[str],
) -> LearnerData:
    """Decode a marked definition; fail clearly on malformed annotations."""
    try:
        fields = validate_learner_fields(json.loads(metadata.get("description", "")))
    except (ValueError, TypeError) as exc:
        raise Error("invalid learner annotation JSON") from exc
    if (fields["scope"] == "sense") != bool(source_sense_id):
        raise Error("only sense learner annotations require sourceSense")
    result = cast("LearnerData", dict(fields))
    result["lexicon"] = lexicon
    result["metadata"] = metadata
    if source_sense_id:
        result["source_sense_id"] = source_sense_id
    if text and text not in original_definitions and fields["scope"] != "word":
        result["plain_language"] = text
    return result
