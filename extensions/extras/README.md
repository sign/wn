# Dictionary extras

Small, manually maintained additions missing from the source lexicons. Keep
these separate from generated Wikidata output so regeneration preserves them.
Docker merges them into their base lexicon using the existing merge utility:

```sh
python extensions/wikidata-lexemes/merge_extension.py extensions/extras/*.xml
```

The English extension adds possessive `'s` (also `’s`) as a particle, covering
possession and association, including independent uses such as “This is John's.”
It does not add the contractions of “is” or “has.”

Its concept ID is `omw-en-extra-possessive-s-y`; dictionary sign links use the
short ID `extra-possessive-s-y`. These IDs must remain stable.
