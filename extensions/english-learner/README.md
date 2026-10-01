# English learner extension

This is an additive extension of `omw-en:1.4` for senses reached by the pinned
5,000-word English frequency list. It preserves the original words, senses,
synsets, and definitions. It supplies examples where a concept has none, plus
optional learner information where useful. It does not introduce new concepts.

## Using the extension

```python
import wn

wn.add('extensions/english-learner/rylo-en-learner.xml.gz')
english = wn.Wordnet('omw-en:1.4')
synset = english.synset('omw-en-09849598-n')
print(synset.definition())     # original WordNet definition
print(synset.examples())       # original plus extension examples
print(synset.learner_data())   # scoped annotations and provenance
```

`Word`, `Sense`, and `Synset` expose `learner_data()`. The web API includes the
same records under `attributes.learner_data`. Generated examples also expose
their provenance under `attributes.example_details`, while `examples` remains
a list of strings. Removing `rylo-en-learner:1.0`
removes its additions without rewriting the base lexicon. Unlike the separate
Wikidata lexeme import, this extension does not need a destructive database
merge.

Docker builds validate the packaged release but do not install it by default.
Use `--build-arg INSTALL_ENGLISH_LEARNER=true` to explicitly opt in.

## Data contract

The package uses standard WN-LMF `LexiconExtension`, `ExternalLexicalEntry`,
`ExternalSense`, and `ExternalSynset` elements. Examples are ordinary `Example`
elements on the existing sense and concept. Example metadata identifies the
source sense, so a synonym's example is not presented as another word's usage.
Original concept examples take precedence: the builder only adds examples to
concepts whose original examples are empty.

Learner annotations are ordinary additional `Definition` elements, marked with
`dc:type="learner-enrichment"`. Their text is a plain-language explanation, or
the unchanged reference definition when only structured notes are supplied.
`dc:description` contains a validated JSON object:

```json
{
  "schema_version": 1,
  "scope": "sense",
  "domains": ["computing"],
  "grammar_notes": ["Usually used as an uncountable noun."]
}
```

Optional fields are `domains`, `register`, `usage`, `grammar_notes`,
`irregular_forms`, and `usage_tips`. List fields contain strings;
`irregular_forms` maps form types to lists of spellings. Omit fields that add
no useful information. No automatic etymologies or redundant comparisons with
other meanings are included.

- `synset` scope supplies a shared explanation for the concept.
- `sense` scope requires native `sourceSense` and applies only to that word's
  meaning; grammatical or register notes must not spread to every synonym.
- Irregular forms default to `sense` scope, because conjugation can depend on
  meaning (for example, lie/lay/lain versus lie/lied/lied). Explicit `word`
  scope requires `word_id` and is available for forms shared by every sense.

`wn.learner.validate_learner_fields` validates this structure. Invalid marked
annotations fail import. Original `.definition()` and `.definitions()` never expose the
annotation container. Native import/export retains source-sense references.

## Generation and review

Generation is offline. There is no request-time model call or UI button.
The input contains the exact lexical form, part of speech, original definition,
existing examples, and native domain/usage evidence. Prior generated training
text is an unreviewed candidate, not a factual authority. The prompt requires
sense-specific examples and permits empty enrichment for straightforward
meanings. Missing, truncated, malformed, or incorrectly targeted outputs are
rejected and recorded for retry.

Native `dc:creator`, `dc:source`, and `status` retain origin and review state.
Model generation and AI review are separate from human review; callers must not
present generated material as human-verified. The release manifest records
coverage and input hashes. The builder refuses to release a corpus with any
remaining example-less target sense or concept. A synonym's examples cannot
satisfy another target word's coverage requirement.

If a meaning cannot be illustrated reliably, keep its generated content out of
the package and list its exact `sense_id` and editorial `reason` in a separate
JSONL file. The builder's explicit `--withheld` input allows these exceptions
and records every one in the manifest. They are not counted as covered or as
published enrichment. Unlisted gaps and records marked unresolved still fail
the build. A package with withheld senses needs further editorial review.

## Reproducing inputs and building

Use the pinned frequency list in this directory. Matching mirrors the dictionary:
case/diacritic-insensitive matching of stored forms, with no inferred morphology.
An uppercase abbreviation is therefore included when it matches a frequent
lowercase form, but generation uses its actual spelling and meaning. Unmatched
frequency words are reported rather than invented as new entries.

The pinned list matches 3,887 frequency words, reaching 21,043 existing senses
in 17,643 concepts. The other 1,113 frequency words have no matching stored form
in this WordNet release. Before enrichment, 6,499 of these concepts have no
examples. Published additions and withheld senses are reported in `manifest.json`.
`quality-audit.json` summarizes the independent Astra audit; its rejection rate
is a review outcome, not a measured accuracy estimate.
`quality-repairs.json` records the correction totals and recovery of previously
withheld senses. Writing attempts, including unsuccessful ones, are preserved in
`quality-repair-attempts.jsonl.xz`.

```sh
python extensions/english-learner/prepare_inventory.py --help
python extensions/english-learner/prepare_candidates.py --help
python extensions/english-learner/generation.py --help
python extensions/english-learner/build_extension.py --help
```

To rebuild the release from its reviewed source records:

```sh
python extensions/english-learner/prepare_inventory.py --output /tmp/learner-inventory
python extensions/english-learner/build_extension.py \
  --inventory /tmp/learner-inventory/inventory.jsonl \
  --records extensions/english-learner/reviewed-records.jsonl.xz \
  --withheld extensions/english-learner/withheld.jsonl \
  --semantic-reviews extensions/english-learner/quality-reviews.jsonl.xz \
  --calibration extensions/english-learner/quality-calibration-decisions.jsonl \
  --output extensions/english-learner/rylo-en-learner.xml.gz
```

`generation.py` supports Ollama and OpenAI-compatible vLLM endpoints, concurrent
batches, deterministic shards, and resume checkpoints keyed by input, prompt,
and model. Each exact sense is assessed once even if several frequency forms
reach it. Generation output is flat JSONL with existing identity fields,
provenance, and optional enrichment. Empty records mean no extra annotation was
needed; they are still useful coverage checkpoints.

`build_extension.py` accepts an inventory and one or more JSONL (or JSONL.xz)
record files. Generated content requires a separate, content-bound Astra approval;
a model name or earlier Luna checkpoint alone cannot release it. Native WordNet
topic labels are checked against original relations and retain their source.
It writes deterministic compressed WN-LMF and a coverage manifest.
The database remains untouched until a caller explicitly installs the package.

## Enforced semantic quality gate

The independent critic receives every proposed field alongside the exact lemma,
part of speech, definition, synonyms, original examples and syntactic frames.
It checks sense fit, grammatical role, factual claims and usage restrictions.
Each review includes a verdict, a sense-specific rationale and field-level issues.
The SHA-256 binds the decision to the content, context, scope and review rubric.
Editing any of these requires another review.

Reviewers return one JSONL record per input, using the same `review_run` for
their calibration and corpus decisions:

```json
{
  "sense_id": "input ID",
  "input_sha256": "input hash",
  "reviewer": "gpt-6-astra",
  "review_run": "run ID",
  "rubric_version": "exact-sense-2",
  "decision": "accept",
  "rationale": "Why every proposed field fits this sense.",
  "issues": []
}
```

`reject` and `uncertain` decisions require one or more issues, each with a
learner `field` name and a specific `reason`. Accepted decisions have no issues.

Each review run must first pass twelve calibration cases: eight known errors
and four valid controls. Passing these checks does not establish a general
accuracy rate. Astra review is still AI review, not human verification.

`apply_reviews.py` requires complete review coverage. It quarantines an entire
sense if any field is rejected or uncertain; it never silently rewrites and
approves a correction. Unreleased rows remain in
`quarantined-records.jsonl.xz`, with the final verdicts in `quality-audit.jsonl.xz`.
The first audit and its rejected source are preserved separately in
`quality-initial-audit.jsonl.xz` and `quality-original-rejected-records.jsonl.xz`;
`quality-repair-history.jsonl.xz` records the subsequent review decisions.
Corrections need fresh review before they can enter a later release.
Native WordNet definitions remain available for withheld senses.

`prepare_corrections.py` verifies the original review hashes and prepares exact
sense context with the flagged fields and reasons. Unsupported optional fields
can be removed with `remove_flagged_fields`; missing examples need new authored
sentences. Both remain unreviewed until another review approves the revised
content. Even deleting all optional fields requires a fresh decision. Generation
receives original WordNet examples to disambiguate short definitions and supports
targeted correction context without creating new meanings.
New Astra-authored corrections record an `author_run` in the source. This identity
is bound into the review hash; the gate rejects decisions from that same run.

To review a new candidate set, prepare exact inputs with `quality_gate.py`, have
independent Astra reviewers return decisions using its rubric and calibration
inputs, then run `apply_reviews.py` before building. Use `--calibration-output`
to prepare blind calibration inputs; do not give reviewers the expected answers
from `quality-calibration.json`. These are offline steps;
CI never calls a model. The committed calibration decisions and compact
`quality-context.jsonl.xz` make the release gate reproducible without downloading
WordNet or accessing the generation machines.

```sh
python extensions/english-learner/check_release.py
```

CI and Docker run this command. It rejects missing, stale, negative or
uncalibrated reviews, validates native topic evidence and coverage, and rebuilds
the XML from approved records to verify the actual packaged text. Changing only
a manifest hash cannot bypass the content review.

## Sources

- Base concepts and definitions: OMW English WordNet 1.4 / Princeton WordNet 3.0.
  Original WordNet attribution and license continue to apply to source material;
  the complete source notices are retained in `SOURCE-LICENSES.txt`.
- Frequency: `first20hours/google-10000-english`, via the pinned dictionary
  snapshot identified in `frequency-source.json`.
- Prior candidate text: `sign/word-sense-disambiguation`,
  `training/data/generated.tar.xz`, generated with `gpt-oss:120b`.
  That repository is MIT-licensed, copyright 2026 Nagish Inc.
- Newly generated material retains the actual model and prompt version in each
  record; native WordNet labels retain separate source attribution.
