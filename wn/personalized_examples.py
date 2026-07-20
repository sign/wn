"""Example personalization for the web API [SIGN-700].

When serving a word's synsets, rewrite example sentences to use the word
being viewed instead of the synonym the example was authored with ("wore a
goofy hat" -> "wore a zany hat" when viewing "zany"). Inflected matches are
handled for noun plurals and third-person-singular verbs ("the best of
motives" -> "the best of motivations"). English only. Deliberately
conservative: an example is returned unchanged unless every guard in
:func:`personalize_example` passes.
"""

import re
from collections.abc import Collection

import inflect  # type: ignore

# A substitutable word is a single lowercase alphabetic word (hyphens ok).
# This excludes multi-word lemmas ("physical process"), proper nouns
# ("Attorney General"), and anything with digits or apostrophes.
_SIMPLE_WORD = re.compile(r'[a-z]+(?:-[a-z]+)*')
# "a"/"an" immediately before the matched synonym.
_PRECEDING_ARTICLE = re.compile(r'\b([Aa]n?) $')
# The only English verbs whose 3rd-person singular is not formed by regular
# suffixation (is, has, does).
_IRREGULAR_3SG = frozenset({'be', 'have', 'do'})

_inflect = inflect.engine()


# Apostrophes (ASCII + U+2019 right single quote) join word characters below
# so "can" never matches inside a contraction, straight- or curly-quoted.
_APOSTROPHES = "'\u2019"


def _word_pattern(word: str) -> re.Pattern:
    # Hyphen and apostrophe count as word characters so "face" never matches
    # inside "about-face" and "can" never matches inside "can't".
    boundary = rf'[\w{_APOSTROPHES}-]'
    return re.compile(
        rf'(?<!{boundary}){re.escape(word)}(?!{boundary})', re.IGNORECASE
    )


def _article_for(word: str) -> str:
    """Return 'a' or 'an' for *word* (sound-aware: an hour, a university)."""
    return _inflect.a(word).split(' ', 1)[0]


def _inflected_variant(word: str, pos: str) -> str | None:
    """Return the noun plural or verb 3rd-person singular of *word*, or None.

    English 3sg verb inflection follows noun-plural suffix morphology
    (cough->coughs, fly->flies, go->goes), so plural_noun serves both — but
    only regularly-suffixed forms are trusted for verbs: irregular *noun*
    plurals ("leaf"->"leaves") are wrong as 3sg ("leafs through"), and
    be/have/do have their own 3sg forms inflect cannot produce.
    """
    if pos == 'n':
        # Words inflect already parses as plural produce garbage plurals
        # ("means" -> "meanss").
        if _inflect.singular_noun(word):
            return None
    elif pos != 'v' or word in _IRREGULAR_3SG:
        return None
    variant = _inflect.plural_noun(word)
    if not variant or variant == word:
        return None
    if pos == 'v':
        regular = (
            variant in (word + 's', word + 'es')
            or (word.endswith('y') and variant == word[:-1] + 'ies')
        )
        if not regular:
            return None
    return variant


def _single_member_match(
    example: str, lemma: str, members: Collection[str], pos: str
) -> tuple[str, str, bool, re.Match] | None:
    """The unique (member, form, is_inflected, match) in *example*, or None.

    Exactly one form of one member may match, exactly once — multiple
    synonyms in one sentence, or overlap with a multi-word member ("course"
    inside "course of action"), make substitution ambiguous. Each member
    matches as-is or as its plural / 3rd-person-singular variant.
    """
    matches: list[tuple[str, str, bool, re.Match]] = []
    for member in members:
        if member == lemma:
            continue
        candidates = [(member, False)]
        if _SIMPLE_WORD.fullmatch(member):
            variant = _inflected_variant(member, pos)
            if variant:
                candidates.append((variant, True))
        for form, inflected in candidates:
            matches.extend(
                (member, form, inflected, m)
                for m in _word_pattern(form).finditer(example)
            )
    return matches[0] if len(matches) == 1 else None


def _fix_article(before: str, lemma: str, inflected: bool) -> str | None:
    """Correct a trailing "a"/"an" in *before* for *lemma*.

    Returns *before* (fixed if needed), or None when the article cannot be
    made right: "a"/"an" never grammatically precedes a plural or 3sg verb,
    so an inflected replacement after an article means the parse is off.
    """
    article = _PRECEDING_ARTICLE.search(before)
    if not article:
        return before
    if inflected:
        return None
    correct = _article_for(lemma)
    if article.group(1)[0].isupper():
        correct = correct.capitalize()
    return before[: article.start(1)] + correct + before[article.end(1) :]


def personalize_example(
    example: str,
    lemma: str,
    forms: Collection[str],
    members: Collection[str],
    pos: str = '',
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
    lemma_variant = _inflected_variant(lemma, pos)
    presence = {lemma, *forms} | ({lemma_variant} if lemma_variant else set())
    if any(_word_pattern(form).search(example) for form in presence):
        return example
    found = _single_member_match(example, lemma, members, pos)
    if found is None:
        return example
    synonym, matched_form, inflected, match = found
    token = match.group(0)
    # The synonym must be a simple word, appearing as-is or sentence-cased.
    if not _SIMPLE_WORD.fullmatch(synonym):
        return example
    if token not in (matched_form, matched_form.capitalize()):
        return example

    # An inflected match needs the lemma inflected the same way; bail when
    # inflect cannot produce a trustworthy form for it.
    replacement = _inflected_variant(lemma, pos) if inflected else lemma
    if replacement is None:
        return example
    if token[0].isupper():
        replacement = replacement.capitalize()

    before = _fix_article(example[: match.start()], lemma, inflected)
    if before is None:
        return example
    return before + replacement + example[match.end() :]
