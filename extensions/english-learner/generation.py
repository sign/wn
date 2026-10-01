"""Generate resumable, unreviewed enrichment with Ollama or an OpenAI-compatible server.

Each output line records one exact lexical sense, its input hash, model,
source identifiers, and optional enrichment. Empty enrichment is intentional:
assessing a meaning does not require adding information to it.
"""

import argparse
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROMPT_VERSION = "english-learner-6"
SYSTEM = """You are a careful English lexicographer enriching existing WordNet meanings.
Return one item for every input id, preserving order. Do not create or merge
meanings. The supplied definition identifies the intended sense; other_meanings are
distractors only and must not be illustrated or added as user-facing
comparisons. Lexical forms retain their exact capitalization (IT is not it).
Prior generated candidates are UNREVIEWED and may be wrong: reuse only text that
accurately expresses this precise sense. Reject invented facts, ambiguous
examples, and unnatural usage. Every example must use the target word in the
supplied part of speech and syntactic frame: a verb sense of check cannot be
illustrated by the noun in write a check, nor by the unrelated verb meaning
verify. Likewise preserve historical or specialist senses rather than replacing
them with common ones. If you cannot express the precise sense naturally and
accurately, return an empty enrichment and a concise unresolved_reason instead
of inventing usage.

Add only information useful beyond the definition; empty enrichment is valid.
plain_language: one short explanation ONLY for an obscure/technical definition.
domains: conventional specialist labels (medical, legal, computing, finance,
biology, chemistry, physics, mathematics, linguistics, religion, music,
military, sport, etc.). Use source topic-domain evidence when given. Do not
label ordinary vocabulary with broad labels such as everyday life or
relationships. Domain is not register; leave unsupported labels absent.
register: ONLY marked register (informal, formal, slang, vulgar, offensive,
archaic, dated, literary). Never neutral. Familiar words such as bank are not
formal just because they have a financial meaning. usage: ONLY helpful region or
context restrictions, without guessing. grammar_notes: ONLY useful sense-
specific constraints such as countability or required complements; do not repeat
the part of speech or basic conjugation. usage_tips: at most two concise
idiomatic constructions or learner pitfalls; no generic advice, obvious
restatement, or comparison to other senses. word_enrichment.irregular_forms:
lexical irregular forms only, as an object mapping form type to a list of
strings (past, past_participle, plural, comparative, superlative). These
describe the exact target sense of the lemma, never the frequency surface word.
Distinguish sense-dependent forms such as lie/lay and lie/lied or hang/hung and
hang/hanged; they will be stored on that sense. Do not add regular forms. Omit
unless certain; do not guess proper-name forms.

If needs_examples=true, add EXACTLY TWO short natural sentences that visibly use
the target word (or a listed inflection) in context, not merely quote or mention
its name. Use one of the supplied matching_forms with appropriate capitalization
and unambiguously express the supplied meaning. If false, OMIT examples. A
person meaning must describe a person, not a pet, emotion, object or different
sense. Medical/scientific examples must avoid making clinical recommendations or
unsupported factual assertions. Use non-graphic educational contexts for sexual
vocabulary; no erotic content. Describe offensive usage without endorsing
stereotypes or directing insults at people. Do not echo source_definition or
original IDs in prose. No invented etymologies, translations, or sign-language
advice.

Quality examples (use these principles, not boilerplate):
- love, noun, beloved person: GOOD: "Good morning, my love," she said to her
  husband. BAD: Her love would always be by his side. The bad sentence could
  describe a feeling, so it does not identify the intended sense.
- bank, financial institution: domains=["finance"] is useful. Do NOT add formal
  register, countable (ordinary and unhelpful), or advice to use "the". Return
  only domains when nothing else is useful.
- AIDS: a medical domain does NOT imply formal register. Examples should show
  contextual use such as a clinic supporting people living with AIDS. Do not
  add claims about transmission, treatment, prognosis, or prevention.
- A clear definition needs no plain_language paraphrase. Most fields should be
  absent for ordinary vocabulary. Never add generic advice about articles,
  frequent collocations, or countability simply to fill a field.
- Existing candidates have deliberately been withheld in this pass: assess the
  source definition independently. Report unresolved_reason rather than guess.

Minimal output examples for needs_examples=false:
- outcome, noun, a result caused by something before it:
  {"id": 0, "enrichment": {}}
- burn, verb, cause a stinging pain:
  {"id": 1, "enrichment": {}}
- grown, adjective, fully developed:
  {"id": 2, "enrichment": {}}
- dynamics, noun, branch of mechanics studying forces and motion:
  {"id": 3, "enrichment": {"domains": ["physics"],
    "grammar_notes": ["Takes a singular verb when naming this field of study."]}}
The first three are ordinary English, not formal, clinical, scientific, or
restricted to a profession. A word's use in a technical sentence does not give
the word a technical register or domain. Do not label adjectives scientific
because the definition mentions animals, or label results physics/chemistry.
Do not add "requires a direct object", "do not use as a noun", "use in context",
or rules about articles. Empty enrichment is usually the best answer.
Proper-name examples: use simple fictional reading, travel, or discussion
contexts, avoiding invented events, quotations, exact dates, or measurements.
For element symbols prefer a laboratory label or sample, not everyday phrases
such as "Fe beams". For state abbreviations prefer written addresses rather
than unnatural spoken sentences such as "we entered IN on the highway".

Correction mode: when correction is supplied, repair EVERY reported issue and
return the COMPLETE replacement enrichment, not a patch. Keep useful unflagged
information only when defensible. Remove unsupported optional claims rather than
guessing a replacement. Avoid needless rewrites. Previous annotations are
untrusted, even when they carry earlier review stamps. A missing example still
requires two correct sentences; merely quoting or defining the word does not
illustrate its grammatical use. For noun medical, "She needed a medical before
joining the team" is valid; "She needed a medical examination" is not.
Do not narrow a definition with invented conditions such as "over time" or
"always". Each example must distinguish this meaning from neighboring meanings:
a general benefit is not necessarily operating profit. The base definition
identifies the intended sense but can contain dated or imprecise factual wording;
do not amplify a factual error into a new assertion. Omit that optional claim or
report unresolved_reason when the intended sense cannot be illustrated reliably.
Use existing_examples and syntactic frames to disambiguate short definitions.
For example, have defined as "have left" means still possess a remaining amount
("How many years do you have left?"), not the perfect tense of leaving a place.
Never reinterpret the target lemma as an auxiliary in a different phrase.
"""

STRING = {"type": "string", "minLength": 1, "maxLength": 500}
LIST = {"type": "array", "items": STRING, "minItems": 1, "maxItems": 3}
FIELDS = {
    "plain_language": STRING,
    **dict.fromkeys(
        ("domains", "register", "usage", "grammar_notes", "usage_tips"), LIST
    ),
}
FIELDS["examples"] = {"type": "array", "items": STRING, "minItems": 2, "maxItems": 2}
SCHEMA = {
    "type": "object",
    "required": ["items"],
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "enrichment"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "integer"},
                    "unresolved_reason": STRING,
                    "enrichment": {
                        "type": "object",
                        "properties": FIELDS,
                        "additionalProperties": False,
                    },
                    "word_enrichment": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "irregular_forms": {
                                "type": "object",
                                "additionalProperties": LIST,
                            }
                        },
                    },
                },
            },
        }
    },
}


PROMPT_HASH = hashlib.sha256(
    (PROMPT_VERSION + SYSTEM + json.dumps(SCHEMA, sort_keys=True)).encode()
).hexdigest()


def input_hash(row):
    value = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def compact(row, index):
    """Bound source text while preserving exact lexical identity and evidence."""
    senses = row["senses"]
    value = {
        "id": index,
        "word": senses[0]["lemma"],
        "pos": row["pos"],
        "definition": row["definitions"],
        "other_meanings": row.get("other_meanings", []),
        "needs_examples": not row["examples"],
        "existing_examples": row["examples"],
        "lexical_entries": [
            {
                "lemma": s["lemma"],
                "matching_forms": s["matching_forms"],
                "forms": s["forms"],
                "tags": s["tags"],
                "syntactic_frames": s["syntactic_frames"],
            }
            for s in senses
        ],
        "topic_domains": [
            r
            for r in row["relations"]
            if r["type"] in ("domain_topic", "domain_region", "domain_usage")
        ],
    }
    if row.get("correction"):
        value["correction"] = row["correction"]
    return value


def validate(item, row, index):
    if not isinstance(item, dict):
        raise ValueError("Response item must be an object")
    if item.get("id") != index:
        raise ValueError("Response ids do not match input order")
    if item.get("unresolved_reason"):
        raise ValueError("Semantic review needed: " + item["unresolved_reason"])
    fields = item.get("enrichment")
    if not isinstance(fields, dict) or set(fields) - set(FIELDS):
        raise ValueError("Invalid enrichment fields")
    for key, value in fields.items():
        values = [value] if key == "plain_language" else value
        if not isinstance(values, list) or not values or len(values) > 3:
            raise ValueError(f"Invalid {key} list")
        if any(not isinstance(v, str) or not v.strip() or len(v) > 500 for v in values):
            raise ValueError(f"Invalid {key} text")
    validate_examples(fields.get("examples", []), row)
    validate_word(item.get("word_enrichment", {}))


def validate_examples(examples, row):
    from wn.morphy import morphy

    if len({text.strip().casefold() for text in examples}) != len(examples):
        raise ValueError("Duplicate examples")
    if row["examples"] and examples:
        raise ValueError("Examples supplied for meaning that already has examples")
    if not row["examples"] and len(examples) != 2:
        raise ValueError("Missing meaning requires two examples")
    forms = [form for sense in row["senses"] for form in sense["matching_forms"]]
    for example in examples:
        # Morphy's suffix rules accept regular inflections (thank/thanked) while
        # preserving the supplied part of speech and proper-name capitalization.
        inflections = set()
        for token in re.findall(r"\b[\w-]+\b", example):
            for lemmas in morphy(token, pos=row.get("pos")).values():
                inflections.update(lemmas)
            if token.istitle():
                for lemmas in morphy(token.lower(), pos=row.get("pos")).values():
                    inflections.update(lemma for lemma in lemmas if lemma.islower())
        if not any(
            re.search(r"(?<!\w)" + re.escape(form) + r"(?!\w)", example)
            or (
                form.islower()
                and re.match(re.escape(form.capitalize()) + r"(?!\w)", example)
            )
            or form in inflections
            for form in forms
        ):
            raise ValueError("Example does not contain an exact matching form")


def validate_word(word):
    if not isinstance(word, dict) or set(word) - {"irregular_forms"}:
        raise ValueError("Invalid word enrichment")
    irregular = word.get("irregular_forms", {})
    if not isinstance(irregular, dict):
        raise ValueError("Invalid irregular forms")
    for key, forms in irregular.items():
        if key not in (
            "past",
            "past_participle",
            "plural",
            "comparative",
            "superlative",
        ):
            raise ValueError("Unknown irregular form type")
        if not isinstance(forms, list) or not forms or len(forms) > 3:
            raise ValueError("Invalid irregular form list")
        if any(not isinstance(f, str) or not f.strip() or len(f) > 100 for f in forms):
            raise ValueError("Invalid irregular form")


def generate(rows, args, error_hint=None):
    source = json.dumps(
        [compact(row, i) for i, row in enumerate(rows)], ensure_ascii=False
    )
    if len(source) + len(SYSTEM) > 18000:
        raise ValueError(
            "Batch source too large for bounded context; reduce batch size"
        )
    payload = {
        "model": args.model,
        "stream": False,
        "think": "low",
        "keep_alive": "30m",
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 2048},
        "format": SCHEMA,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": source},
        ],
    }
    if not args.model.startswith("gpt-oss"):
        payload.pop("think", None)
    if error_hint:
        payload["messages"].append(
            {
                "role": "user",
                "content": "A previous response failed validation: "
                + error_hint
                + ". Correct that issue while preserving the supplied meaning.",
            }
        )
    endpoint_path = "/api/chat"
    if args.api == "openai":
        endpoint_path = "/v1/chat/completions"
        payload = {
            "model": args.model,
            "messages": payload["messages"],
            "temperature": 0,
            "max_tokens": 2048,
            "reasoning_effort": "low",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "learner_enrichment",
                    "schema": SCHEMA,
                },
            },
        }
    request = Request(
        args.endpoint.rstrip("/") + endpoint_path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=args.timeout) as response:
            result = json.load(response)
    except HTTPError as error:
        detail = error.read(1000).decode(errors="replace")
        raise ValueError(f"Server HTTP {error.code}: {detail}") from error
    result = normalize_response(result, args.api)
    parsed = json.loads(result["message"]["content"])
    if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
        raise ValueError("Response must contain an items list")
    items = parsed["items"]
    if len(items) != len(rows):
        raise ValueError("Response does not cover every input")
    for i, (item, row) in enumerate(zip(items, rows, strict=True)):
        discard_surplus_examples(item, row)
        validate(item, row, i)
    return items, result


def discard_surplus_examples(item, row):
    """Keep original examples when the model volunteers replacements."""
    if row["examples"] and isinstance(item, dict):
        enrichment = item.get("enrichment")
        if isinstance(enrichment, dict):
            enrichment.pop("examples", None)


def normalize_response(result, api):
    if not isinstance(result, dict):
        raise ValueError("Server response must be an object")
    if api == "openai":
        if not isinstance(result.get("choices"), list) or not result["choices"]:
            raise ValueError("Server choices must be a nonempty list")
        choice = result["choices"][0]
        if not isinstance(choice, dict):
            raise ValueError("Server choice must be an object")
        usage = result.get("usage") or {}
        if not isinstance(usage, dict):
            raise ValueError("Server usage must be an object")
        result = {
            "message": choice["message"],
            "done_reason": choice["finish_reason"],
            "eval_count": usage.get("completion_tokens", 0),
        }
    if result.get("done_reason") != "stop":
        raise ValueError("Model response was truncated")
    if not isinstance(result.get("message"), dict):
        raise ValueError("Server message must be an object")
    if not isinstance(result["message"].get("content"), str):
        raise ValueError("Server message content must be text")
    return result


def expand_inventory(rows, context_rows=None):
    """Assess exact senses once; provide known forms and prompt-only distractors."""
    from wn.personalized_examples import _inflected_variant

    meanings = {}
    for row in context_rows if context_rows is not None else rows:
        for sense in row["senses"]:
            meaning = {
                "pos": row.get("pos"),
                "definition": row.get("definitions", [""])[0],
            }
            if meaning not in meanings.setdefault(sense["lemma"], []):
                meanings[sense["lemma"]].append(meaning)
    selected = {}
    for row in sorted(rows, key=lambda value: value["frequency_rank"]):
        for sense in row["senses"]:
            if sense["sense_id"] in selected:
                continue
            lemma = sense["lemma"]
            forms = [
                lemma,
                *sense["matching_forms"],
                *[f["form"] for f in sense.get("forms", [])],
            ]
            if re.fullmatch(r"[a-z]+(?:-[a-z]+)*", lemma):
                variant = _inflected_variant(lemma, row.get("pos"))
                if variant:
                    forms.append(variant)
            target = {**sense, "matching_forms": list(dict.fromkeys(forms))}
            distractors = [
                m
                for m in meanings[lemma]
                if m["definition"] not in row.get("definitions", [])
            ][:8]
            selected[sense["sense_id"]] = {
                **row,
                "senses": [target],
                "other_meanings": distractors,
            }
    return list(selected.values())


def output_record(row, item, args):
    sense = row["senses"][0]
    return {
        "word": sense["lemma"],
        "frequency_word": row["word"],
        "frequency_rank": row["frequency_rank"],
        "word_id": sense["entry_id"],
        "sense_id": sense["sense_id"],
        "synset_id": row["synset_id"],
        "base_definition": row["definitions"][0],
        "input_hash": input_hash(row),
        "prompt_version": PROMPT_VERSION,
        "model": args.model,
        "model_revision": args.model_revision,
        "prompt_hash": PROMPT_HASH,
        "creator": args.model,
        "source": f"{args.api}:{args.model}/{PROMPT_VERSION}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "unreviewed",
        **({"requires_semantic_review": True} if row.get("correction") else {}),
        **item["enrichment"],
        **item.get("word_enrichment", {}),
    }


def process_batch(batch, args):
    """Retry individual rejected inputs; one malformed response cannot stop a run."""
    try:
        items, _ = generate(batch, args)
        return [
            output_record(row, item, args)
            for row, item in zip(batch, items, strict=True)
        ], []
    except (ValueError, OSError, KeyError, TypeError, IndexError) as error:
        errors = []
        records = []
        for row in batch:
            last_error = error
            for _ in range(2):
                try:
                    items, _ = generate([row], args, error_hint=str(last_error))
                    records.append(output_record(row, items[0], args))
                    break
                except (
                    ValueError,
                    OSError,
                    KeyError,
                    TypeError,
                    IndexError,
                ) as retry_error:
                    last_error = retry_error
            else:
                errors.append(
                    {
                        "sense_id": row["senses"][0]["sense_id"],
                        "input_hash": input_hash(row),
                        "error": str(last_error),
                    }
                )
        return records, errors


def read_completed(path, model, model_revision=None):
    if not path.exists():
        return set()
    try:
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid checkpoint JSON in {path}; repair any interrupted trailing "
            "line before resuming, so successful checkpoints are not overwritten"
        ) from error
    return {
        r["input_hash"]
        for r in records
        if r["model"] == model
        and r["prompt_version"] == PROMPT_VERSION
        and r.get("prompt_hash") == PROMPT_HASH
        and r.get("model_revision") == model_revision
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--context-inventory", type=Path)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--api", choices=("ollama", "openai"), default="ollama")
    parser.add_argument("--model", default="gpt-oss:120b")
    parser.add_argument("--model-revision")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if not 0 <= args.shard < args.shards or not 1 <= args.batch_size <= 8:
        parser.error("Require 0 <= shard < shards and 1 <= batch-size <= 8")
    if not 1 <= args.workers <= 16:
        parser.error("Use 1-16 workers, within the server's configured concurrency")
    rows = expand_inventory(
        [
            json.loads(line)
            for line in args.inventory.read_text(encoding="utf-8").splitlines()
            if line
        ],
        [
            json.loads(line)
            for line in args.context_inventory.read_text(encoding="utf-8").splitlines()
            if line
        ]
        if args.context_inventory
        else None,
    )
    rows = [row for i, row in enumerate(rows) if i % args.shards == args.shard]
    completed = read_completed(args.output, args.model, args.model_revision)
    rows = [row for row in rows if input_hash(row) not in completed]
    if args.limit:
        rows = rows[: args.limit]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(rows)} pending senses; {len(completed)} checkpoints", flush=True)
    batches = [
        rows[i : i + args.batch_size] for i in range(0, len(rows), args.batch_size)
    ]
    done, failures = 0, 0
    started = time.monotonic()
    with (
        ThreadPoolExecutor(max_workers=args.workers) as pool,
        args.output.open("a", encoding="utf-8") as output,
        args.output.with_suffix(".errors.jsonl").open("a", encoding="utf-8") as errors,
    ):
        futures = [pool.submit(process_batch, batch, args) for batch in batches]
        for future in as_completed(futures):
            records, rejected = future.result()
            for record in records:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
            for error in rejected:
                errors.write(json.dumps(error, ensure_ascii=False) + "\n")
            output.flush()
            errors.flush()
            done += len(records)
            failures += len(rejected)
            print(
                f"{done}/{len(rows)} senses; {failures} rejected; "
                f"{time.monotonic() - started:.1f}s",
                flush=True,
            )
    if failures:
        raise SystemExit(f"{failures} senses require retry; successful outputs saved")


if __name__ == "__main__":
    main()
