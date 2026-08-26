"""Parity with the TypeScript original.

These tests exist to catch silent drift in the two things the agents' behaviour
actually depends on: the exact prompt text, and the exact envelope it is
wrapped in.
"""

import random
from pathlib import Path

import pytest

from app.agents.registry import AGENT_IDS, agents, render_transcript
from app.llm import build_messages
from app.orchestrator import last_agent_speaker, pick_next_speaker
from app.schemas import ChatMessage

TS_AGENTS = Path(__file__).resolve().parents[2] / "app" / "lib" / "agents.ts"


def test_prompts_load_and_are_whole():
    """Guards against a truncated, empty, or wrong file being loaded silently.

    The prompts are the product, so they are deliberately NOT pinned to a hash —
    they are meant to be edited. These check the shape survives an edit.
    """
    for agent in agents().values():
        assert len(agent.system_prompt) > 4000, f"{agent.id} prompt looks truncated"
        assert agent.system_prompt.startswith(f'You are "{agent.name}"')
        # The rule that stops the agents breaking the fourth wall.
        assert 'Never refer to them as "the user"' in agent.system_prompt or                'Never say "the user"' in agent.system_prompt,                f"{agent.id} lost its address-the-person rule"


def test_the_two_agents_with_a_safety_carve_out_still_have_it():
    """The Introspector and The Behaviorist each hold a value that must not be
    applied to abuse. Losing this carve-out is the highest-consequence possible
    prompt regression, so it gets its own test."""
    for agent_id in ("introspector", "behaviorist"):
        prompt = agents()[agent_id].system_prompt
        assert "EXCEPTION — safety:" in prompt, f"{agent_id} lost its safety exception"
        assert "abuse" in prompt and "safety and autonomy" in prompt


def test_agent_names_match_the_frontend():
    """The display names are shared state: the prompts instruct the agents to
    refer to each other by these exact strings, and the UI renders them. If the
    two sides drift, the agents start naming someone who does not exist."""
    ts = TS_AGENTS.read_text(encoding="utf-8")
    for agent in agents().values():
        assert f'name: "{agent.name}"' in ts, f"{agent.name} missing from agents.ts"


def test_frontend_no_longer_carries_the_prompts():
    """The prompts belong to the backend only — one source of truth, and not
    16KB of prompt text in every visitor's bundle."""
    ts = TS_AGENTS.read_text(encoding="utf-8")
    assert "systemPrompt" not in ts
    assert "You are \"The" not in ts


def test_render_transcript_matches_ts_shape():
    """Port of renderTranscript: "Speaker: content", blank line between."""
    t = [
        ChatMessage(role="user", content="should I quit?"),
        ChatMessage(role="behaviorist", content="what have you tried?"),
        ChatMessage(role="gardener", content="who else is in this?"),
    ]
    assert render_transcript(t) == (
        "User: should I quit?\n\n"
        "The Behaviorist: what have you tried?\n\n"
        "The Gardener: who else is in this?"
    )


def test_prompt_envelope_is_pinned():
    """Pinned because the envelope measurably shapes the reply.

    Deliberately not the TypeScript original. Two earlier versions were
    measured and both produced uniform turns: "Respond as X with your next
    message" gave 48% over 100 words and 1% under 15; "say the one thing you
    would say next" gave 0% over 40 words with 81% inside one narrow band.
    This version names the SITUATION rather than a length, and legitimises the
    short end and the long end together. The pin catches UNdeliberate edits.
    """
    agent = agents()["introspector"]
    t = [ChatMessage(role="user", content="hi")]
    system, human = build_messages(agent, t)
    assert system.content == agent.system_prompt
    assert human.content == (
        "Here is the conversation so far:\n\n"
        "User: hi\n\n"
        "You are The Introspector. You have just heard all of this.\n\n"
        "The person has just spoken. You can answer with a single question if "
        "that is what you actually have.\n\n"
        "A single sentence is a complete turn. So is a question, or agreeing in "
        "four words. Take a full paragraph only when you have a case nobody here "
        "has made yet — and then make it properly.\n\n"
        "Say what you would actually say next."
    )


def test_envelope_legitimises_both_ends():
    """The failure mode in both earlier versions was naming only one end.

    Whichever end is named becomes the only length produced, so the permission
    has to be two-sided in every envelope, whatever the situation.
    """
    agent = agents()["behaviorist"]
    cases = [
        [ChatMessage(role="user", content="hi")],
        [ChatMessage(role="user", content="hi"),
         ChatMessage(role="behaviorist", content="what have you tried")],
        [ChatMessage(role="user", content="hi"),
         ChatMessage(role="gardener", content="who else is in this")],
    ]
    for t in cases:
        _, human = build_messages(agent, t)
        assert "A single sentence is a complete turn" in human.content
        assert "Take a full paragraph only when" in human.content


def test_last_agent_speaker_skips_the_user():
    assert last_agent_speaker([ChatMessage(role="user", content="a")]) is None
    t = [
        ChatMessage(role="user", content="a"),
        ChatMessage(role="gardener", content="b"),
        ChatMessage(role="user", content="c"),
    ]
    assert last_agent_speaker(t) == "gardener"


def test_first_speaker_can_be_any_agent():
    seen = {pick_next_speaker(None, rng=random.Random(s)) for s in range(60)}
    assert seen == set(AGENT_IDS)


def test_double_turn_rate_is_about_one_in_four():
    rng = random.Random(1234)
    n = 20_000
    repeats = sum(pick_next_speaker("gardener", rng=rng) == "gardener" for _ in range(n))
    assert 0.23 < repeats / n < 0.27


def test_non_repeat_turns_are_split_evenly_between_the_other_two():
    rng = random.Random(99)
    counts = {"introspector": 0, "behaviorist": 0}
    for _ in range(20_000):
        pick = pick_next_speaker("gardener", rng=rng)
        if pick != "gardener":
            counts[pick] += 1
    lo, hi = sorted(counts.values())
    assert hi / lo < 1.06, f"uneven split: {counts}"


# ── Rhythm ──────────────────────────────────────────────────────────────────
#
# A fixed instruction produces a fixed length, whichever length it names. These
# check that the envelope varies with the situation instead, which is the only
# reason to expect the turns to vary.


def rhythm_for(agent_id, transcript):
    from app.llm import rhythm_note
    return rhythm_note(agents()[agent_id], transcript)


def test_holding_the_floor_is_told_not_to_restate():
    t = [
        ChatMessage(role="user", content="should I go?"),
        ChatMessage(role="behaviorist", content="what have you tried so far?"),
    ]
    note = rhythm_for("behaviorist", t)
    assert "spoke last" in note
    assert "restate" in note


def test_a_long_previous_turn_is_named_back_to_the_agent():
    """The 'gets shorter the second time' move, made explicit."""
    long_turn = " ".join(["word"] * 120)
    t = [
        ChatMessage(role="user", content="should I go?"),
        ChatMessage(role="behaviorist", content=long_turn),
        ChatMessage(role="gardener", content="who else is in this?"),
    ]
    note = rhythm_for("behaviorist", t)
    assert "120 words" in note
    assert "does not need to be that long" in note


def test_a_short_previous_turn_does_not_trigger_the_shorten_nudge():
    t = [
        ChatMessage(role="user", content="should I go?"),
        ChatMessage(role="behaviorist", content="what have you tried?"),
        ChatMessage(role="gardener", content="who else is in this?"),
    ]
    note = rhythm_for("behaviorist", t)
    assert "does not need to be that long" not in note
    # It should be pointed at the agent who just spoke instead.
    assert "The Gardener just spoke" in note


def test_another_agent_speaking_invites_a_direct_short_answer():
    t = [
        ChatMessage(role="user", content="should I go?"),
        ChatMessage(role="introspector", content="what do you feel about it?"),
    ]
    note = rhythm_for("gardener", t)
    assert "The Introspector just spoke" in note
    assert "four words" in note


def test_opening_the_conversation():
    note = rhythm_for("gardener", [ChatMessage(role="user", content="should I go?")])
    assert "person has just spoken" in note
    assert "single question" in note


def test_the_note_actually_changes_between_situations():
    """If every situation produced the same note there would be no mechanism."""
    long_turn = " ".join(["word"] * 120)
    situations = [
        [ChatMessage(role="user", content="q")],
        [ChatMessage(role="user", content="q"),
         ChatMessage(role="behaviorist", content="short one")],
        [ChatMessage(role="user", content="q"),
         ChatMessage(role="behaviorist", content=long_turn),
         ChatMessage(role="gardener", content="g")],
        [ChatMessage(role="user", content="q"),
         ChatMessage(role="gardener", content="g")],
    ]
    notes = {rhythm_for("behaviorist", t) for t in situations}
    assert len(notes) == 4, f"only {len(notes)} distinct notes across 4 situations"
