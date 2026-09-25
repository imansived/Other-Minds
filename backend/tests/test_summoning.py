"""Asking for a mind by name must get that mind.

Reported from testing: "when I want a particular opinion of one agent I even
call them explicitly but still randomly anyone was coming." The room was
ignoring the one thing the person had said unambiguously.

The draw is still random everywhere else — that is the product. This only
carves out the case where the person named someone.
"""

import random

import pytest

from app.agents.registry import AGENT_IDS, AGENT_NAMES
from app.orchestrator import choose_speaker, pick_next_speaker, summoned
from app.schemas import ChatMessage


def user(text: str) -> ChatMessage:
    return ChatMessage(role="user", content=text)


# Every rng below is seeded to a draw that would return something ELSE, so a
# passing test cannot be the random draw agreeing by luck.
def rigged() -> random.Random:
    return random.Random(0)


@pytest.mark.parametrize("agent_id", AGENT_IDS)
@pytest.mark.parametrize(
    "shape",
    [
        "{name}, what do you think?",
        "{name} what do you make of this",
        "The {name} — your take?",
        "I'd like {name}'s opinion here.",
        "can we hear from the {name} on this one",
        "{lower}, say more about that",
    ],
)
def test_a_named_mind_is_the_one_that_speaks(agent_id, shape):
    """Display name, bare word, lowercase, possessive, with or without "the"."""
    bare = AGENT_NAMES[agent_id].removeprefix("The ")
    text = shape.format(name=bare, lower=bare.lower())
    assert summoned([user(text)]) == agent_id, f"missed the summons in {text!r}"
    assert choose_speaker([user(text)], rng=rigged()) == agent_id


def test_no_name_means_the_ordinary_draw():
    """The randomness is the product. This must not quietly replace it."""
    t = [user("I think I want a divorce. We have two kids.")]
    assert summoned(t) is None
    picked = {choose_speaker(t, rng=random.Random(s)) for s in range(60)}
    assert picked == set(AGENT_IDS), "the draw stopped reaching every mind"


def test_naming_two_minds_is_a_topic_not_a_request():
    """"The Gardener and the Behaviorist are both missing something" asks for
    neither of them in particular — picking one arbitrarily would be worse than
    drawing, because it would look deliberate."""
    t = [user("The Gardener and the Behaviorist are both missing something.")]
    assert summoned(t) is None
    picked = {choose_speaker(t, rng=random.Random(s)) for s in range(60)}
    assert picked == set(AGENT_IDS)


def test_the_summons_is_served_once():
    """Once the named mind has answered, "hear another mind" must move on.

    The name is still sitting in the transcript, so a rule that looked further
    back than the last message would re-elect the same mind forever and the
    button would never work again.
    """
    t = [
        user("Introspector, what do you think?"),
        ChatMessage(role="introspector", content="You used the word twice."),
    ]
    assert summoned(t) is None
    for seed in range(40):
        assert choose_speaker(t, allow_same=False, rng=random.Random(seed)) != (
            "introspector"
        )


def test_naming_the_mind_that_just_spoke_asks_for_more_from_it():
    """A summons beats allow_same: it is a request, not a mistake to correct."""
    t = [
        user("What should I do?"),
        ChatMessage(role="gardener", content="Who else is in this?"),
        user("Gardener, say more about that."),
    ]
    assert summoned(t) == "gardener"
    assert choose_speaker(t, allow_same=False, rng=rigged()) == "gardener"


def test_only_the_person_can_summon():
    """A mind naming another mind is disagreement, not turn-taking.

    They refer to each other by name constantly — the prompts require it — so
    reading a summons out of an agent's turn would hand the floor to whoever was
    mentioned last and collapse the whole draw.
    """
    t = [
        user("What should I do?"),
        ChatMessage(
            role="behaviorist",
            content="The Introspector is guessing at a motive there.",
        ),
    ]
    assert summoned(t) is None
    picked = {choose_speaker(t, rng=random.Random(s)) for s in range(60)}
    assert len(picked) > 1, "an agent's mention of another agent acted as a summons"


def test_an_empty_or_agentless_transcript_is_safe():
    assert summoned([]) is None
    assert summoned([ChatMessage(role="gardener", content="hello")]) is None


def test_a_mention_in_an_older_message_does_not_linger():
    """Only the last message counts."""
    t = [
        user("Behaviorist, what do you think?"),
        ChatMessage(role="behaviorist", content="What have you tried?"),
        user("I tried leaving for two weeks."),
    ]
    assert summoned(t) is None


def test_substrings_do_not_summon():
    """Word boundaries: a mind is summoned by its name, not by a fragment."""
    for text in [
        "I am introspecting about this a lot lately.",
        "Her behaviour has been strange.",
        "We went to a garden party.",
    ]:
        assert summoned([user(text)]) is None, f"false summons on {text!r}"


def test_pick_next_speaker_is_unchanged():
    """The draw itself was not touched — the summons sits in front of it."""
    rng = random.Random(1234)
    n = 20_000
    repeats = sum(pick_next_speaker("gardener", rng=rng) == "gardener" for _ in range(n))
    assert 0.23 < repeats / n < 0.27
