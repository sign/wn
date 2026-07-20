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


def test_personalize_example_sound_aware_articles():
    # inflect resolves onsets the vowel-letter rule gets wrong
    sub = personalize_example
    assert (
        sub('it was a strange sight', 'unusual', ['unusual'], ['strange', 'unusual'])
        == 'it was an unusual sight'
    )
    assert (
        sub('an odd word', 'university-level', [], ['odd', 'university-level'])
        == 'a university-level word'
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
    # member appearing only inside a contraction is not a match
    contraction = "he can't swim"
    assert sub(contraction, 'commode', ['commode'], ['can', 'commode']) == contraction
    # oddly-cased token (not lowercase or sentence case)
    shouting = 'GOOFY behavior'
    assert sub(shouting, 'zany', ['zany'], ['goofy', 'zany']) == shouting


def test_personalize_example_articles_for_one_compounds():
    sub = personalize_example
    # "one-..." compounds are "w" onsets: "a one-sided account"
    assert (
        sub('a biased account', 'one-sided', ['one-sided'], ['biased', 'one-sided'])
        == 'a one-sided account'
    )
    assert (
        sub('a heavy task', 'onerous', ['onerous'], ['heavy', 'onerous'])
        == 'an onerous task'
    )


def test_personalize_example_inflects_noun_plurals():
    sub = personalize_example
    # regular plural member -> plural of the viewed word
    assert (
        sub(
            'he acted with the best of motives',
            'motivation',
            ['motivation'],
            ['motive', 'motivation', 'need'],
            'n',
        )
        == 'he acted with the best of motivations'
    )
    # irregular plural member detected, viewed word pluralized regularly
    assert (
        sub('the treaty had no teeth in it', 'fang', ['fang'], ['tooth', 'fang'], 'n')
        == 'the treaty had no fangs in it'
    )
    # the viewed word's own plural counts as "already present"
    echoes = 'she could hear echoes of her own footsteps'
    assert sub(echoes, 'echo', ['echo'], ['echo', 'replication'], 'n') == echoes
    # an article before a plural match means the parse is off — skipped
    quiz = 'a motives quiz'
    assert sub(quiz, 'motivation', ['motivation'], ['motive'], 'n') == quiz


def test_personalize_example_inflects_third_person_verbs():
    sub = personalize_example
    assert (
        sub('The smoker coughs all day', 'hack', ['hack'], ['cough', 'hack'], 'v')
        == 'The smoker hacks all day'
    )
    # other tenses are still out of reach
    froze = 'She froze in place'
    assert sub(froze, 'halt', ['halt'], ['freeze', 'halt'], 'v') == froze
    # irregular 3sg lemmas (be/have/do) are never inflected
    exists = 'The problem exists'
    assert sub(exists, 'be', ['be'], ['exist', 'be'], 'v') == exists
    # irregular noun plurals are not trusted as 3sg ("wolf" -> "wolves")
    gobbles = 'He gobbles his food'
    assert sub(gobbles, 'wolf', ['wolf'], ['gobble', 'wolf'], 'v') == gobbles
