# Frequent English word examples

Original, sense-specific example sentences for gaps in `omw-en:1.4` and the
merged Wikidata extension. Existing examples are preserved. Sentences are added
to both the sense and its synset because the dictionary API displays synset
examples.

New examples carry native `learner-example` metadata with their source sense,
AI creator, source URL, and an `unreviewed` status. This records AI authorship
without implying independent or human review. The API exposes that provenance
in `example_details` and does not substitute synonyms into these sentences.

## Selection and coverage

`top1000.tsv` pins the 1,000 most frequent spellings **with dictionary entries**
in the [FrequencyWords English 2018 list](https://github.com/hermitdave/FrequencyWords/blob/master/content/2018/en/en_50k.txt).
Matching is case insensitive and includes the forms already in the dictionary.
The selection reaches source rank 1,075. Unrepresented spellings (including
contractions, subtitle fragments and some inflections) are skipped, rather than
inventing dictionary senses for them. Counts and original ranks are retained.
Case folding can match an acronym or letter, so examples use that entry's actual
meaning: `ISN` is an information network, not a contraction of “isn't”.

There are 452 new sentences. Combined with the existing data, every selected
word has an example containing that spelling. This is word-level coverage,
not a claim that every sense of a polysemous word has an example. All six
existing senses of **to** receive examples. Additional sentences cover missing
function-word senses, such as different uses of **for**, **it**, **all**,
**some**, **this**, **when**, **can**, and **they**.

The live records of all 290 Wikidata lexemes represented in the selection were
retrieved during the review on 2026-10-17. `wikidata-revisions.json` records their
revision IDs. A Wikidata sense can be inspected at
`https://www.wikidata.org/wiki/Lexeme:L248738#L248738-S1`; a reviewed revision at
`https://www.wikidata.org/w/index.php?oldid=2544768486`.

Definitions, lexical categories, forms, and existing example qualifiers were
checked before assigning sentences to sense IDs. Wiktionary's English
definitions were also checked for unusual uses. Register notes distinguish
archaic, dialectal, technical, and uncommon usages. `needs-review.json` lists
17 Wikidata senses whose gloss or part of speech needs clarification; they
are left unchanged. For example, the noun **missing** has a verb-like gloss,
and the adjective **return** is glossed “give back”. These senses should be
corrected at the source before attaching an example. Other meanings of these
words already have examples.

Wikidata sometimes supplies a lexeme-level example without a sense qualifier
(for example, the movement example for **to**). Such examples must not be copied
to every sense: the time and infinitive meanings need different sentences.

## Loading and verification

After installing `omw-en:1.4` and merging `wikidata-lexemes/output/en.xml`, run:

```sh
python extensions/english-examples/enrich.py
```

The Docker build runs this automatically. All target sense/form pairs are
validated before writing. Repeated imports do not duplicate sentences; no
definitions, senses, or existing examples are replaced. The final coverage
check fails the build if any of the 1,000 spellings lacks an example containing
the word. It checks word boundaries, so “he” inside “the” does not count.

The enrichment is applied after XML import so it also reaches base WordNet
senses, and survives regeneration of the Wikidata XML. No network requests or
text generation occur during builds or API requests.

To verify against an isolated populated database, set `WN_DATA_DIR` to that
database's directory before running the command. The regression tests use
small temporary databases and do not require downloads.

## Attribution

The original sentences follow this repository's MIT license. Definition
snapshots are included to make sense assignments reviewable and retain their
upstream licenses: [Wikidata lexicographical data](https://www.wikidata.org/wiki/Wikidata:Licensing)
is CC0; synthetic `-WKT1` definitions originate in the corresponding English
[Wiktionary](https://en.wiktionary.org/) entry and are CC BY-SA. Base WordNet
definitions follow the [Princeton WordNet license](https://wordnet.princeton.edu/license-and-commercial-use).
The FrequencyWords ranking is by Hermit Dave, derived from OpenSubtitles2018,
and [licensed CC BY-SA 4.0](https://github.com/hermitdave/FrequencyWords#license).
`top1000.tsv` is a filtered excerpt of that ranking under the same license.
