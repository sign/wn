"""Example personalization for the web API [SIGN-700].

When serving a word's synsets, rewrite example sentences to use the word
being viewed instead of the synonym the example was authored with ("wore a
goofy hat" -> "wore a zany hat" when viewing "zany"). English only.
Deliberately conservative: an example is returned unchanged unless every
guard in :func:`personalize_example` passes.
"""

import re
from collections.abc import Collection

# A substitutable word is a single lowercase alphabetic word (hyphens ok).
# This excludes multi-word lemmas ("physical process"), proper nouns
# ("Attorney General"), and anything with digits or apostrophes.
_SIMPLE_WORD = re.compile(r'[a-z]+(?:-[a-z]+)*')
# "a"/"an" immediately before the matched synonym.
_PRECEDING_ARTICLE = re.compile(r'\b([Aa]n?) $')
# The vowel-letter article rule is wrong for "you"-, "w"-, and silent-h
# onsets; these closed lists cover the common cases. 'u'-initial words stay
# ambiguous ("an unusual" vs "a university") and get no article at all.
_SILENT_H = ('hour', 'honest', 'honor', 'honour', 'heir')
_GLIDE_ONSET_PREFIXES = ('eu', 'ew')
_GLIDE_ONSET_WORDS = ('one', 'once')


def _word_pattern(word: str) -> re.Pattern:
    # Hyphen counts as a word character so "face" never matches inside
    # "about-face".
    return re.compile(rf'(?<![\w-]){re.escape(word)}(?![\w-])', re.IGNORECASE)


def _article_for(word: str) -> str | None:
    """Return 'a' or 'an' for *word*, or None when the onset is ambiguous."""
    if word.startswith(_SILENT_H):
        return 'an'
    if word.startswith(_GLIDE_ONSET_PREFIXES) or word in _GLIDE_ONSET_WORDS:
        return 'a'
    if word.startswith(('one-', 'once-')):
        return 'a'
    if word.startswith('one'):
        # Underived "one..." words split: "oneness" is a "w" onset ("a"),
        # "onerous" is a vowel onset ("an") — ambiguous, so no article.
        return None
    if word.startswith('u'):
        return None
    return 'an' if word[0] in 'aeio' else 'a'


def personalize_example(
    example: str, lemma: str, forms: Collection[str], members: Collection[str]
) -> str:
    """Rewrite *example* to use *lemma* in place of a synonym, if safe.

    Returns the example unchanged unless all guards pass; see the module
    docstring for the rationale.
    """
    # The viewed word must itself be a simple word.
    if not _SIMPLE_WORD.fullmatch(lemma):
        return example
    # Never rewrite quotations (716 of the 780 quoted examples in omw-en are
    # attributed citations; substituting inside them fabricates quotes).
    if any(quote in example for quote in ('"', '“', '”')):
        return example
    # The viewed word (in any inflection) must not already be present.
    if any(_word_pattern(form).search(example) for form in {lemma, *forms}):
        return example
    # Exactly one other member may match, exactly once — multiple synonyms
    # in one sentence, or overlap with a multi-word member ("course" inside
    # "course of action"), make substitution ambiguous.
    matches = [
        (member, found)
        for member in dict.fromkeys(members)
        if member != lemma and (found := _word_pattern(member).findall(example))
    ]
    if len(matches) != 1 or len(matches[0][1]) != 1:
        return example
    synonym, (token,) = matches[0]
    # The synonym must be a simple word, appearing as-is or sentence-cased.
    if not _SIMPLE_WORD.fullmatch(synonym):
        return example
    if token not in (synonym, synonym.capitalize()):
        return example

    match = _word_pattern(synonym).search(example)
    assert match is not None
    before = example[: match.start()]
    replacement = lemma.capitalize() if token[0].isupper() else lemma

    article = _PRECEDING_ARTICLE.search(before)
    if article:
        correct = _article_for(lemma)
        if correct is None:
            return example
        if article.group(1)[0].isupper():
            correct = correct.capitalize()
        before = before[: article.start(1)] + correct + before[article.end(1) :]

    return before + replacement + example[match.end() :]
