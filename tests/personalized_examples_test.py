from wn.personalized_examples import personalize_example


def test_personalize_example_substitutes_synonym():
    sub = personalize_example
    assert (
        sub('wore a goofy hat', 'zany', ['zany', 'zanier'], ['goofy', 'silly', 'zany'])
        == 'wore a zany hat'
    )


def test_personalize_example_preserves_capitalization():
    assert (
        personalize_example(
            'Touristry is big business',
            'tourism',
            ['tourism'],
            ['touristry', 'tourism'],
        )
        == 'Tourism is big business'
    )


def test_personalize_example_fixes_articles():
    sub = personalize_example
    # a -> an
    assert (
        sub(
            'it was a reversal of policy',
            'about-face',
            ['about-face'],
            ['reversal', 'about-face'],
        )
        == 'it was an about-face of policy'
    )
    # an -> a
    assert (
        sub('an interlocking of arms', 'mesh', ['mesh'], ['interlocking', 'mesh'])
        == 'a mesh of arms'
    )
    # sentence-initial article keeps its capitalization
    assert (
        sub('An interlocking of arms', 'mesh', ['mesh'], ['interlocking', 'mesh'])
        == 'A mesh of arms'
    )
    # silent h takes "an"
    assert (
        sub('a moment of rest', 'hour', ['hour', 'hours'], ['moment', 'hour'])
        == 'an hour of rest'
    )
    # glide onsets take "a"
    assert (
        sub('an insignia on the door', 'emblem', ['emblem'], ['insignia', 'emblem'])
        == 'an emblem on the door'
    )
    assert (
        sub('an insignia here', 'eutectic', ['eutectic'], ['insignia', 'eutectic'])
        == 'a eutectic here'
    )


def test_personalize_example_skips_ambiguous_article():
    # 'u...' onset is ambiguous ("a university" vs "an umbrella") — untouched
    example = 'it was a strange sight'
    assert (
        personalize_example(example, 'unusual', ['unusual'], ['strange', 'unusual'])
        == example
    )
    # ...but a 'u' lemma with no preceding article substitutes fine
    assert (
        personalize_example(
            'the sight was strange', 'unusual', ['unusual'], ['strange', 'unusual']
        )
        == 'the sight was unusual'
    )


def test_personalize_example_guards():
    sub = personalize_example
    # quotations are never rewritten
    quote = '"Vengeance is mine; I will repay, saith the Lord"--Romans 12:19'
    assert sub(quote, 'payback', ['payback'], ['vengeance', 'payback']) == quote
    # the viewed word already present (any inflection)
    shook = 'his hands shook'
    assert sub(shook, 'shake', ['shake', 'shook'], ['didder', 'shake']) == shook
    # multi-word viewed lemma
    assert sub('a goofy hat', 'off the wall', [], ['goofy']) == 'a goofy hat'
    # capitalized viewed lemma (proper nouns)
    assert sub('the president spoke', 'Chief Executive', [], ['president']) == (
        'the president spoke'
    )
    # no member in the example
    respiring = 'The patient is respiring'
    assert sub(respiring, 'breathe', ['breathe'], ['respire']) == respiring
    # inflected member is not an exact match
    froze = 'She froze in place'
    assert sub(froze, 'halt', ['halt'], ['freeze', 'halt']) == froze
    # two members present -> ambiguous
    huffed = 'he huffed and puffed'
    assert sub(huffed, 'chuff', ['chuff'], ['huffed', 'puffed', 'chuff']) == huffed
    # member repeated -> ambiguous
    twice = 'goofy is as goofy does'
    assert sub(twice, 'zany', ['zany'], ['goofy', 'zany']) == twice
    # single-word member overlapping a multi-word member
    embarked = 'embarked on a course of action'
    members = ['course', 'course of action', 'path']
    assert sub(embarked, 'path', ['path'], members) == embarked
    # member appearing only inside a hyphenated compound is not a match
    compound = 'an about-face on policy'
    members = ['face', 'countenance']
    assert sub(compound, 'countenance', ['countenance'], members) == compound
    # oddly-cased token (not lowercase or sentence case)
    shouting = 'GOOFY behavior'
    assert sub(shouting, 'zany', ['zany'], ['goofy', 'zany']) == shouting
