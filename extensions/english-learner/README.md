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
examples. The release adds 14,053 example sentences to 6,424 of those concepts
and assesses all 21,043 target senses. Of these, 20,922 senses passed review;
121 remain withheld for editorial review. See `manifest.json` for
field-level coverage and every explicit exception.

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
  --output extensions/english-learner/rylo-en-learner.xml.gz
```

`generation.py` supports Ollama and OpenAI-compatible vLLM endpoints, concurrent
batches, deterministic shards, and resume checkpoints keyed by input, prompt,
and model. Each exact sense is assessed once even if several frequency forms
reach it. Generation output is flat JSONL with existing identity fields,
provenance, and optional enrichment. Empty records mean no extra annotation was
needed; they are still useful coverage checkpoints.

`build_extension.py` accepts an inventory and one or more JSONL (or JSONL.xz)
record files. Generated records must carry an independent AI-review checkpoint;
raw generator output is rejected. Native WordNet labels retain their source.
It writes deterministic compressed WN-LMF and a coverage manifest.
The database remains untouched until a caller explicitly installs the package.

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
