"""The Introspector may propose a reading. It may not promote one into a fact.

Every case here is a PAIR built on the same words. If a test could be passed by
deleting a phrase from the prompts, it would be testing vocabulary; these are
built so the offending phrase appears on both sides and only the epistemic
status differs. That is the behaviour being protected:

    observation → interpretation → uncertainty

The bad examples are the shapes named in review, plus two taken verbatim from
generated transcripts.
"""

import pytest

from app.epistemics import (
    is_marked_as_interpretation,
    mind_reading_share,
    unmarked_mind_reading,
)

# (bad, good) — the same claim, asserted then owned.
PAIRS = [
    (
        "You already know you want to leave.",
        "I wonder if you already know you want to leave.",
    ),
    (
        "You are afraid because leaving would make it real.",
        "You are afraid because leaving would make it real — or that is my read, "
        "and I could be wrong.",
    ),
    (
        "What you really want is permission to stop.",
        "What you really want might be permission to stop.",
    ),
    (
        "Deep down you have already decided.",
        "Deep down you may have already decided. That is a guess from here.",
    ),
    (
        "You don't actually want the promotion.",
        "Perhaps you don't actually want the promotion.",
    ),
    (
        "You're using your parents as an excuse.",
        "I suspect you're using your parents as an excuse, though I can't know "
        "that from here.",
    ),
    (
        "The real reason you stayed is that you were frightened.",
        "The real reason you stayed could be that you were frightened.",
    ),
    # Straight from a generated transcript, and the exact sentence that prompted
    # this module.
    (
        "It means you already know what you want to do.",
        "It suggests you already know what you want to do.",
    ),
]


@pytest.mark.parametrize("bad,good", PAIRS)
def test_the_assertion_is_flagged_and_the_reading_is_not(bad, good):
    assert unmarked_mind_reading(bad) == [bad], f"not flagged: {bad!r}"
    assert unmarked_mind_reading(good) == [], f"wrongly flagged: {good!r}"


def test_this_is_not_a_phrase_ban():
    """The proof that the detector reads epistemics, not vocabulary.

    Every banned-sounding phrase appears on the passing side of some pair, so a
    mind that keeps its sharp readings and simply owns them scores clean.
    """
    for bad, good in PAIRS:
        stem = bad.rstrip(".").lower()
        # The good version still contains the substance of the bad one, minus
        # punctuation and the added marker.
        shared = [w for w in stem.split() if len(w) > 4]
        assert any(w in good.lower() for w in shared), (
            f"the pair no longer shares its wording, so it tests phrasing: {good!r}"
        )
    assert mind_reading_share([g for _, g in PAIRS]) == 0.0
    assert mind_reading_share([b for b, _ in PAIRS]) == 1.0


def test_a_question_is_never_an_assertion():
    """Asking hands the turn back. That is the behaviour, not a loophole."""
    assert unmarked_mind_reading("Do you already know what you want?") == []
    assert is_marked_as_interpretation("What you really want is what, exactly?")


def test_repeating_the_person_back_is_an_observation():
    """Quoting someone's own words is the opposite of claiming hidden access."""
    for line in [
        "You said you already know what you want.",
        "You keep returning to the idea of leaving.",
        "You called it an excuse, in your own words.",
    ]:
        assert unmarked_mind_reading(line) == [], f"observation flagged: {line!r}"


def test_the_reviewed_good_example_passes_whole():
    """The shape asked for in review, end to end: observation, then reading."""
    turn = (
        "You keep returning to the idea of leaving. I wonder if part of you has "
        "already made the decision, while another part is afraid of what follows."
    )
    assert unmarked_mind_reading(turn) == []


def test_ordinary_speech_is_not_flagged():
    """A detector that fires on normal turns is worse than none — the number
    stops distinguishing anything. These are real turns from the corpus."""
    for line in [
        "How many times in the last month did you make that drive?",
        "Have you told them about the job offer yet?",
        "That changes the shape of the problem.",
        "Your sister has carried the other forty-nine weeks of this.",
        "I don't know. Nothing you have said settles it either way.",
    ]:
        assert unmarked_mind_reading(line) == [], f"false positive: {line!r}"


def test_the_recommended_hedge_forms_actually_count_as_hedges():
    """The house style names specific structural forms. The detector has to
    accept them, or it penalises the exact phrasing the prompt asks for.

    "That makes me wonder…" was scored as an unowned assertion, because the
    marker was anchored to "i wonder".
    """
    for line in [
        "That makes me wonder whether you already know what you want.",
        "One reading is that what you really want is permission to stop.",
        "It leaves me wondering if deep down you have already decided.",
    ]:
        assert unmarked_mind_reading(line) == [], f"recommended form flagged: {line!r}"

    # ...without clearing an assertion that merely contains the word.
    assert unmarked_mind_reading("No wonder you already know you want to leave.")


def test_curly_apostrophes_are_not_an_escape_hatch():
    """Gemini writes ’ and the patterns are spelled with '.

    Found by reading a transcript the metric had already scored 0/15: the model
    had written "You're afraid that…" with a curly apostrophe and sailed
    straight through. A detector with a silent hole is worse than no detector,
    because the clean number gets believed.
    """
    straight = "You're afraid that leaving would make it real."
    curly = straight.replace("'", "’")
    assert unmarked_mind_reading(straight), "the control case stopped working"
    # Flagged sentences come back normalised — the apostrophe is straightened on
    # the way in, so a report shows one spelling whatever the model wrote.
    assert unmarked_mind_reading(curly) == [straight], "curly apostrophe slipped through"

    # And the marked version still passes with either apostrophe.
    assert unmarked_mind_reading("I wonder if you’re afraid that it would "
                                 "make it real.") == []


def test_one_bad_sentence_condemns_the_turn_not_the_paragraph():
    """A long turn is flagged for the sentence that earned it, so a failure can
    be read rather than merely counted."""
    turn = (
        "You have mentioned the move three times now. You already know you want "
        "to go. Whether the timing works is a different question."
    )
    assert unmarked_mind_reading(turn) == ["You already know you want to go."]
