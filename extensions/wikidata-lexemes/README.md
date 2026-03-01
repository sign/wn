# Wikidata Lexemes

Our multilingual wordnet covers nouns, verbs, adjectives, and adverbs well, but lacks function words (prepositions, conjunctions, determiners, pronouns, etc.).

This module creates Global WordNet LMF extension files using Wikidata Lexemes to fill that gap.

## Setup

Install dependencies:

```bash
pip install ijson requests tqdm
```

Download the lexemes dump (~400MB):

```bash
curl -O https://dumps.wikimedia.org/wikidatawiki/entities/latest-lexemes.json.bz2
```

## Usage

Run the extension generator:

```bash
python create_extensions.py
```

This will:
1. Filter lexemes to exclude nouns, verbs, adjectives, adverbs, and phrases
2. Build an interlingual index (ILI) linking senses across languages via English
3. Generate XML extension files in `extensions/` for each language

## Output

The script generates ~130 language-specific XML files in Global WordNet LMF format:
- `extensions/en.xml` - English
- `extensions/de.xml` - German
- `extensions/ja.xml` - Japanese
- etc.

Each file contains lexical entries with:
- Lemma and part of speech
- Sense definitions and glosses
- Usage examples (where available)
- Sense relations (synonyms, antonyms, hypernyms, hyponyms)
- "Interlingual index" like links to English senses
