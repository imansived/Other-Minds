"""A mind that was just challenged should be the one answering.

The draw is blind to what was said, so a mind named by another got the right of
reply only as often as chance allowed. These pin the pull that fixes that, and
the thing it must not become: a guarantee that shuts the third mind out.

There is deliberately no change to what the challenged mind is TOLD. A live
check (six challenges, answered under the old note and under one saying "this
was aimed at you") found no tic under either, no visible gain — the old note's
replies already took the challenge up 6 of 6 times — and turns about 13 words
longer. So the note stays as it was.
"""

import random

import pytest

from app.agents.registry import AGENT_IDS
from app.config import settings
from app.orchestrator import (
    addressed,
    choose_speaker,
    pick_next_speaker,
    right_of_reply,
)
from app.schemas import ChatMessage


def user(text="should I go?"):
    return ChatMessage(role="user", content=text)


def mind(agent_id, text):
    return ChatMessage(role=agent_id, content=text)


# ── Who has been called on ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "speaker,named,text",
    [
        ("gardener", "behaviorist", "The Behaviorist is counting trips; that misses who else drives."),
        ("behaviorist", "introspector", "The Introspector is treating a feeling as a fact."),
        ("introspector", "gardener", "I'd read that differently from the Gardener."),
        ("gardener", "behaviorist", "behaviorist's number says nothing about why."),
    ],
)
def test_a_mind_naming_another_calls_it_on(speaker, named, text):
    assert addressed([user(), mind(speaker, text)]) == named


def test_naming_nobody_calls_nobody():
    assert addressed([user(), mind("gardener", "That rent doesn't cost what it takes to stay.")]) is None


def test_naming_both_others_is_talking_about_them_not_to_either():
    both = "The Behaviorist and the Introspector are answering different questions."
    assert addressed([user(), mind("gardener", both)]) is None


def test_a_mind_naming_itself_calls_nobody():
    assert addressed([user(), mind("gardener", "As the Gardener, I'd start elsewhere.")]) is None


def test_once_the_person_has_spoken_nobody_is_owed_a_reply():
    """The room answers the person; a quarrel from three messages ago lapses."""
    t = [
        user(),
        mind("gardener", "The Behaviorist is counting trips."),
        user("actually she drove up every weekend"),
    ]
    assert addressed(t) is None


def test_an_empty_transcript_is_safe():
    assert addressed([]) is None
    assert right_of_reply([]) is None


# ── The pull ────────────────────────────────────────────────────────────────

CHALLENGE = [user(), mind("gardener", "The Behaviorist is counting trips; that misses who else drives.")]


def share_named(transcript, *, allow_same, n=20_000, seed=7):
    rng = random.Random(seed)
    want = addressed(transcript)
    return sum(
        choose_speaker(transcript, allow_same=allow_same, rng=rng) == want
        for _ in range(n)
    ) / n


def test_the_challenged_mind_answers_more_often_than_chance():
    """Even odds between the two others before; 0.4 + 0.6 * 0.5 = 70% now."""
    share = share_named(CHALLENGE, allow_same=False)
    assert 0.67 < share < 0.73, share
    assert share > 0.5 + 0.1, "no better than the blind draw"


def test_it_is_a_pull_not_a_guarantee():
    """If the challenged mind always answered, a quarrel could never be joined."""
    rng = random.Random(3)
    picks = {choose_speaker(CHALLENGE, allow_same=False, rng=rng) for _ in range(300)}
    assert picks == {"behaviorist", "introspector"}, picks


def test_the_mind_that_just_spoke_is_never_the_one_called_back():
    rng = random.Random(5)
    picks = {choose_speaker(CHALLENGE, allow_same=False, rng=rng) for _ in range(300)}
    assert "gardener" not in picks


def test_a_summons_still_beats_the_pull():
    """The person asking for a mind by name outranks one mind calling on another."""
    t = [
        user(),
        mind("gardener", "The Behaviorist is counting trips."),
        user("introspector, what do you make of that?"),
    ]
    rng = random.Random(1)
    assert {choose_speaker(t, rng=rng) for _ in range(100)} == {"introspector"}


def test_four_turns_between_two_minds_hand_the_floor_back_to_the_draw():
    """A quarrel is the point; one that has locked the third mind out is not."""
    t = [
        user(),
        mind("gardener", "The Behaviorist is counting trips."),
        mind("behaviorist", "The Gardener is changing the subject."),
        mind("gardener", "The Behaviorist is avoiding the question."),
        mind("behaviorist", "The Gardener is still not answering."),
    ]
    assert right_of_reply(t, rng=random.Random(0)) is None
    # …and the third mind now gets an equal shot at speaking.
    rng = random.Random(9)
    picks = [choose_speaker(t, allow_same=False, rng=rng) for _ in range(4000)]
    assert 0.45 < picks.count("introspector") / len(picks) < 0.55


def test_three_turns_is_not_yet_a_closed_pair():
    t = [
        user(),
        mind("gardener", "The Behaviorist is counting trips."),
        mind("behaviorist", "The Gardener is changing the subject."),
        mind("gardener", "The Behaviorist is avoiding the question."),
    ]
    # Only three minds' turns: the pull is still live.
    assert any(right_of_reply(t, rng=random.Random(s)) == "behaviorist" for s in range(50))


def test_the_draw_itself_is_untouched():
    """The pull sits in front of pick_next_speaker; it never edits it."""
    rng = random.Random(1234)
    n = 20_000
    repeats = sum(pick_next_speaker("gardener", rng=rng) == "gardener" for _ in range(n))
    assert 0.23 < repeats / n < 0.27


def test_with_no_pull_configured_the_old_behaviour_returns(monkeypatch):
    monkeypatch.setattr(settings, "reply_pull", 0.0)
    assert 0.47 < share_named(CHALLENGE, allow_same=False) < 0.53


# ── Choosing a mind without typing its name ─────────────────────────────────
#
# Replying to one of a mind's messages is the plainest way to ask for it. It has
# to beat every other way a speaker gets picked, or the person's choice is just
# one more input to the draw.


@pytest.mark.parametrize("target", AGENT_IDS)
def test_a_chosen_mind_always_answers(target):
    t = [user(), mind("gardener", "What have you tried?"), user("I tried, it went nowhere.")]
    rng = random.Random(11)
    for allow_same in (True, False):
        assert {choose_speaker(t, allow_same=allow_same, rng=rng, address_to=target) for _ in range(200)} == {target}


def test_choosing_the_mind_that_just_spoke_is_honoured():
    """A reply to the last message is a request for more from it, not an error."""
    t = [user(), mind("gardener", "What have you tried?")]
    assert choose_speaker(t, allow_same=False, address_to="gardener") == "gardener"


def test_a_chosen_mind_outranks_a_name_typed_in_the_message():
    t = [user(), mind("gardener", "Who else is in this?"), user("introspector, what do you think?")]
    assert choose_speaker(t, address_to="behaviorist") == "behaviorist"


def test_a_chosen_mind_outranks_the_pull():
    """Someone was challenged by name, but the person picked a different mind."""
    t = [user(), mind("gardener", "The Behaviorist is counting trips.")]
    rng = random.Random(2)
    assert {choose_speaker(t, allow_same=False, rng=rng, address_to="introspector") for _ in range(100)} == {"introspector"}


def test_an_id_that_is_not_a_mind_is_ignored():
    t = [user("should I go?")]
    rng = random.Random(3)
    picks = {choose_speaker(t, rng=rng, address_to="the-user") for _ in range(100)}  # type: ignore[arg-type]
    assert picks <= set(AGENT_IDS) and len(picks) > 1


def test_no_address_leaves_every_other_rule_as_it_was():
    t = [user(), mind("gardener", "The Behaviorist is counting trips.")]
    assert 0.67 < share_named(t, allow_same=False) < 0.73


def test_both_routes_accept_and_honour_the_address():
    """The contract the browser relies on, through the real request models."""
    from app.schemas import NextSpeakerRequest, TurnRequest

    body = {
        "transcript": [{"role": "user", "content": "hi"}],
        "addressTo": "introspector",
    }
    assert NextSpeakerRequest.model_validate(body).address_to == "introspector"
    assert TurnRequest.model_validate(body).address_to == "introspector"
    assert NextSpeakerRequest.model_validate({"transcript": body["transcript"]}).address_to is None
    with pytest.raises(Exception):
        NextSpeakerRequest.model_validate({**body, "addressTo": "nobody"})
