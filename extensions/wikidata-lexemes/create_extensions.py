#!/usr/bin/env python3
import bz2
import json
from functools import cache
from pathlib import Path

import ijson
import requests
from tqdm import tqdm

DATA_PATH = Path(__file__).parent / "latest-lexemes.json.bz2"
EXTENSIONS_DIR = Path(__file__).parent / "output"
EXTRAS_DIR = Path(__file__).parent / "extras"

# Mapping for languages with non-standard OMW lexicon IDs
BASE_LEXICON_MAP = {
    "de": ("odenet", "1.4"),
}

SKIP_POS = {
    # Covered in WordNet already
    "noun",
    "proper noun",
    "agent noun",
    "verb",
    "proper verb",  # to Zoom, to Google
    "phrasal verb",  # get over, find out
    "adverb",
    "adjective",
    "satellite adjective",
    "proper adjective",
    # Not covered, and less useful for us
    "prefix",
    "suffix",
    "interfix",
    "adjectival suffix",
    "nominal suffix",
    "verbal suffix",
    "adverbial suffix",
    "combining form",
    "postpositive adjective",
    "digraph",  # two letters representing one sound
    "contraction",
    "letter",
    "name suffix",
    "symbol",
    # Phrases
    "phrase",
    "saying",
    "idiom",
    "proverb",
    "everyday collocation",
    "interjectional locution",
    "formulaic language",
    "verbal locution",
    "prepositional syntagma",
    "phrasal template",
    "adjectival phrase",
    "noun phrase",
    "verb phrase",
    "nominal locution",
    "multiword expression",
    "conjunctive locution",
    "conjunctive adverb",
    "collocation",
    "attributive locution",
    "slogan",
    # Entities?
    "initialism",
    "demonym",
    "national demonym",
    "toponym",
}

SENSE_RELATIONS = {
    "P5973": "similar",  # synonym
    "P5974": "antonym",  # antonym
    "P5975": "hyponym",  # troponym of (more specific)
    "P6593": "hypernym",  # hyperonym (more general)
}

ENGLISH_LANG_Q = "Q1860"


@cache
def fetch_wikidata_entity(q_code: str) -> dict:
    cache_path = EXTRAS_DIR / f"{q_code}.json"
    if cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        print("fetch_wikidata_entity", q_code)
        url = f"https://www.wikidata.org/wiki/Special:EntityData/{q_code}.json"
        headers = {"User-Agent": "WikidataLexemesBot/1.0 (https://github.com/sign-language-processing/dictionary)"}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        EXTRAS_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    entities = data["entities"]
    return entities.get(q_code) or next(iter(entities.values()))


@cache
def get_label(q_code: str) -> str:
    entity = fetch_wikidata_entity(q_code)
    labels = entity.get("labels", {})
    if "en" in labels:
        return labels["en"]["value"].lower()
    if labels:
        return next(iter(labels.values()))["value"].lower()
    return q_code


@cache
def get_language_iso(q_code: str) -> str | None:
    entity = fetch_wikidata_entity(q_code)
    claims = entity.get("claims", {})
    iso_claim = claims.get("P218", [])  # ISO 639-1 code
    if iso_claim:
        mainsnak = iso_claim[0].get("mainsnak", {})
        datavalue = mainsnak.get("datavalue")
        if datavalue:
            return datavalue["value"]
    return None

def stream_lexemes():
    with bz2.open(DATA_PATH, "rb") as f:
        yield from ijson.items(f, "item")


def collect_kept_sense_ids() -> tuple[set[str], set[tuple[str, str]]]:
    """First pass: collect sense IDs and (lang, sense_id) pairs we're keeping."""
    kept_sense_ids: set[str] = set()
    kept_lang_senses: set[tuple[str, str]] = set()  # (lang_iso, sense_id) pairs
    print("Step 1a: Collecting kept sense IDs...")
    for lexeme in tqdm(stream_lexemes(), desc="Collecting"):
        pos_q = lexeme.get("lexicalCategory")
        if not pos_q:
            continue
        pos_name = get_label(pos_q)
        if pos_name in SKIP_POS or pos_name == "abbreviation":
            continue
        lemmas = lexeme.get("lemmas", {})
        for lang_iso in lemmas:
            for sense in lexeme.get("senses", []):
                kept_sense_ids.add(sense["id"])
                kept_lang_senses.add((lang_iso, sense["id"]))
    print(f"  Found {len(kept_sense_ids)} kept sense IDs")
    print(f"  Found {len(kept_lang_senses)} kept (lang, sense) pairs")
    return kept_sense_ids, kept_lang_senses


def has_valid_abbreviation_relation(lexeme: dict, kept_sense_ids: set[str]) -> bool:
    """Check if abbreviation has at least one relation to a kept sense."""
    for sense in lexeme.get("senses", []):
        claims = sense.get("claims", {})
        for prop in SENSE_RELATIONS:
            for claim in claims.get(prop, []):
                mainsnak = claim.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue")
                if (datavalue
                        and datavalue.get("type") == "wikibase-entityid"
                        and datavalue["value"]["id"] in kept_sense_ids):
                    return True
    return False


def filter_lexemes() -> tuple[list[dict], set[tuple[str, str]]]:
    """Filter lexemes to only include relevant POS."""
    kept_sense_ids, kept_lang_senses = collect_kept_sense_ids()

    filtered = []
    print("Step 1b: Filtering lexemes by POS...")
    for lexeme in tqdm(stream_lexemes(), desc="Filtering"):
        pos_q = lexeme.get("lexicalCategory")
        if not pos_q:
            continue
        pos_name = get_label(pos_q)
        if pos_name in SKIP_POS:
            continue
        if (pos_name == "abbreviation"
                and not has_valid_abbreviation_relation(lexeme, kept_sense_ids)):
            continue
        filtered.append(lexeme)

    print(f"  Kept {len(filtered)} lexemes")
    return filtered, kept_lang_senses


def _collect_senses_and_translations(lexemes: list[dict]):
    """Collect English senses and translation mappings from lexemes."""
    english_senses: set[str] = set()
    translations: dict[str, list[str]] = {}
    for lexeme in tqdm(lexemes, desc="Indexing"):
        is_english = lexeme.get("language") == ENGLISH_LANG_Q
        for sense in lexeme.get("senses", []):
            sense_id = sense["id"]
            if is_english:
                english_senses.add(sense_id)
            claims = sense.get("claims", {})
            for claim in claims.get("P5972", []):
                mainsnak = claim.get("mainsnak", {})
                datavalue = mainsnak.get("datavalue")
                if datavalue and datavalue.get("type") == "wikibase-entityid":
                    target_id = datavalue["value"]["id"]
                    translations.setdefault(sense_id, []).append(target_id)
    return english_senses, translations


def build_ili_index(lexemes: list[dict]) -> dict[str, str]:
    """Build mapping from sense ID to English ILI."""
    print("Step 2: Building ILI index...")
    english_senses, translations = _collect_senses_and_translations(lexemes)

    ili_index: dict[str, str] = {}
    for sense_id in english_senses:
        ili_index[sense_id] = sense_id.lower()

    for sense_id, targets in translations.items():
        if sense_id in ili_index:
            continue
        for target in targets:
            if target in english_senses:
                ili_index[sense_id] = target.lower()
                break

    print(f"  English senses: {len(english_senses)}")
    print(f"  Senses with ILI: {len(ili_index)}")
    return ili_index


def _extract_sense_examples(lexeme: dict, lang_iso: str) -> dict[str, list[str]]:
    """Build mapping of sense_id -> examples from P5831 claims."""
    sense_examples: dict[str, list[str]] = {}
    for claim in lexeme.get("claims", {}).get("P5831", []):
        mainsnak = claim.get("mainsnak", {})
        datavalue = mainsnak.get("datavalue")
        if not datavalue or datavalue.get("type") != "monolingualtext":
            continue
        text_value = datavalue.get("value", {})
        if text_value.get("language") != lang_iso:
            continue
        example_text = text_value.get("text", "")
        qualifiers = claim.get("qualifiers", {})
        for qual in qualifiers.get("P6072", []):
            qual_datavalue = qual.get("datavalue")
            if qual_datavalue and qual_datavalue.get("type") == "wikibase-entityid":
                target_sense = qual_datavalue["value"]["id"]
                sense_examples.setdefault(target_sense, []).append(example_text)
    return sense_examples


def _build_sense_relations(
    sense: dict, lang_iso: str,
    kept_lang_senses: set[tuple[str, str]],
) -> list[str]:
    """Build XML relation strings for a sense."""
    relations = []
    claims = sense.get("claims", {})
    for prop, rel_type in SENSE_RELATIONS.items():
        for claim in claims.get(prop, []):
            mainsnak = claim.get("mainsnak", {})
            datavalue = mainsnak.get("datavalue")
            if datavalue and datavalue.get("type") == "wikibase-entityid":
                target_id = datavalue["value"]["id"]
                if (lang_iso, target_id) not in kept_lang_senses:
                    continue
                target_synset = f"wikidata-{lang_iso}-{target_id}"
                relations.append(
                    f'        <SenseRelation relType="{rel_type}"'
                    f' target="{target_synset}"/>'
                )
    return relations


def build_xml_entry(
    lexeme: dict, lang_iso: str,
    ili_index: dict[str, str],
    kept_lang_senses: set[tuple[str, str]],
) -> tuple[str, list[str]] | None:
    lexeme_id = lexeme["id"]
    lemmas = lexeme.get("lemmas", {})
    if lang_iso not in lemmas:
        return None
    lemma = lemmas[lang_iso]["value"]

    pos_q = lexeme.get("lexicalCategory")
    if not pos_q:
        return None
    pos_name = get_label(pos_q)

    senses = lexeme.get("senses", [])
    if not senses:
        return None

    sense_examples = _extract_sense_examples(lexeme, lang_iso)

    sense_entries = []
    synset_entries = []
    for sense in senses:
        sense_id = sense["id"]
        glosses = sense.get("glosses", {})
        gloss = glosses.get(lang_iso, {}).get("value", "")
        relations = _build_sense_relations(sense, lang_iso, kept_lang_senses)
        examples = sense_examples.get(sense_id, [])

        synset_id = f"wikidata-{lang_iso}-{sense_id}"
        ili = ili_index.get(sense_id, synset_id)
        ili_attr = f' ili="{ili}"'
        sense_content = (
            f'      <Sense id="{sense_id}"'
            f' synset="{synset_id}"{ili_attr}>\n'
        )
        sense_content += f'        <Definition>{escape_xml(gloss)}</Definition>\n'
        for example in examples:
            sense_content += f'        <Example>{escape_xml(example)}</Example>\n'
        if relations:
            sense_content += "\n".join(relations) + "\n"
        sense_content += "      </Sense>"
        sense_entries.append(sense_content)

        synset_content = f'    <Synset id="{synset_id}"{ili_attr}>\n'
        synset_content += f'      <Definition>{escape_xml(gloss)}</Definition>\n'
        synset_content += "    </Synset>"
        synset_entries.append(synset_content)

    if not sense_entries:
        return None

    entry_xml = (
        f'    <LexicalEntry id="{lexeme_id}">\n'
        f'      <Lemma writtenForm="{escape_xml(lemma)}"'
        f' partOfSpeech="{escape_xml(pos_name)}"/>\n'
        + "\n".join(sense_entries)
        + "\n    </LexicalEntry>"
    )
    return entry_xml, synset_entries


def escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def get_xml_header(lang_iso: str) -> str:
    base_id, base_version = BASE_LEXICON_MAP.get(lang_iso, (f"omw-{lang_iso}", "1.4"))
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE LexicalResource SYSTEM "https://globalwordnet.github.io/schemas/WN-LMF-1.4.dtd">
<LexicalResource xmlns:dc="https://globalwordnet.github.io/schemas/dc/">
  <LexiconExtension id="wikidata-{lang_iso}"
                    label="Wikidata {lang_iso.upper()} Lexemes Extension"
                    language="{lang_iso}"
                    email="amit@nagish.com"
                    license="https://creativecommons.org/publicdomain/zero/1.0/"
                    version="1.0">
    <Extends id="{base_id}" version="{base_version}"/>
'''


XML_FOOTER = '''  </LexiconExtension>
</LexicalResource>
'''


def write_all_extensions(
    lexemes: list[dict],
    ili_index: dict[str, str],
    kept_lang_senses: set[tuple[str, str]],
):
    """Write XML extensions for all languages."""
    EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)

    file_handlers: dict[str, any] = {}
    entry_counts: dict[str, int] = {}
    synsets_by_lang: dict[str, list[str]] = {}

    print("Step 3: Writing all language extensions...")
    try:
        for lexeme in tqdm(lexemes, desc="Writing"):
            lang_q = lexeme.get("language")
            if not lang_q:
                continue

            lang_iso = get_language_iso(lang_q)
            if not lang_iso:
                continue

            result = build_xml_entry(lexeme, lang_iso, ili_index, kept_lang_senses)
            if not result:
                continue

            entry, synsets = result

            if lang_iso not in file_handlers:
                output_path = EXTENSIONS_DIR / f"{lang_iso}.xml"
                file_handlers[lang_iso] = open(output_path, "w", encoding="utf-8")  # noqa: SIM115
                file_handlers[lang_iso].write(get_xml_header(lang_iso))
                entry_counts[lang_iso] = 0
                synsets_by_lang[lang_iso] = []

            file_handlers[lang_iso].write(entry + "\n")
            synsets_by_lang[lang_iso].extend(synsets)
            entry_counts[lang_iso] += 1

    finally:
        for lang_iso, f in file_handlers.items():
            for synset in synsets_by_lang.get(lang_iso, []):
                f.write(synset + "\n")
            f.write(XML_FOOTER)
            f.close()

    print(f"  Wrote {len(file_handlers)} language files:")
    for lang_iso in sorted(entry_counts.keys()):
        print(f"    {lang_iso}: {entry_counts[lang_iso]} entries")


def main():
    lexemes, kept_lang_senses = filter_lexemes()
    ili_index = build_ili_index(lexemes)
    write_all_extensions(lexemes, ili_index, kept_lang_senses)


if __name__ == "__main__":
    main()
