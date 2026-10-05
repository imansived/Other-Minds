"""Guards on the prompt rules that were arrived at by trial and error.

Each assertion corresponds to a failure actually observed in generated
conversations, so the comments record WHY the rule exists — otherwise the
obvious "cleanup" is to put the deleted instruction back.

Nothing here calls the API. These check the prompt text; whether the model obeys
is a separate question only a live run answers.

Layout note: a prompt is `<agent>.md` (the lens) + `_house.md` (shared rules),
composed in registry.py. House rules are asserted against the composed prompt so
that a mind which somehow stopped receiving the house style fails loudly.
"""

import re

import pytest

from app.agents.registry import (
    AGENT_IDS,
    AGENT_NAMES,
    PROMPT_DIR,
    agents,
    compose_prompt,
)

HOUSE = (PROMPT_DIR / "_house.md").read_text(encoding="utf-8")


def lens(agent_id: str) -> str:
    """The agent's OWN file, without the shared house style."""
    return (PROMPT_DIR / f"{agent_id}.md").read_text(encoding="utf-8")


# ── Structure ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_prompt_is_lens_plus_house(agent_id):
    """The split is the maintenance fix: house rules exist in ONE file.

    They used to be copy-pasted into all three prompts, so every edit had to be
    made three times or silently drift.
    """
    prompt = agents()[agent_id].system_prompt
    assert prompt.startswith(f'You are "{AGENT_NAMES[agent_id]}"')
    assert "# How this conversation works" in prompt
    assert lens(agent_id).rstrip() in prompt


def test_house_names_are_filled_from_the_registry():
    """A fourth mind must not leave three prompts claiming there are three."""
    assert "__ALL_NAMES__" in HOUSE, "the token is what makes this substitutable"
    for prompt in (a.system_prompt for a in agents().values()):
        assert "__ALL_NAMES__" not in prompt
        for name in AGENT_NAMES.values():
            assert name in prompt

    # Adding a mind changes the sentence, without touching any prompt file.
    composed = compose_prompt("introspector", "You are X.", "Minds: __ALL_NAMES__.")
    assert "The Introspector, The Behaviorist and The Gardener" in composed


# ── Hypothesis is not fact (the headline requirement) ───────────────────────


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_hypothesis_is_not_fact(agent_id):
    """Live transcripts produced confident mind-reading that sounded insightful.

    "You only use that word when you're forcing yourself toward something you
    dread" is unfalsifiable and stated as established. The rule has to name the
    failure AND block the over-correction, or the agents turn into disclaimers.
    """
    prompt = agents()[agent_id].system_prompt
    assert "Hypothesis is not fact" in prompt
    assert "You cannot see inside them" in prompt
    assert "must be said as one" in prompt
    # The anti-timidity half. Without it the fix is worse than the bug.
    assert "This is not licence to hedge." in prompt
    assert "not clinical throat-clearing" in prompt


def test_introspector_has_the_three_beat_pattern():
    """Its lens is the one that can fabricate, so it gets the concrete shape.

    The house rule ("hypothesis is not fact") is abstract and was not enough on
    its own: a live run still produced "It suggests that you already know what
    you want to do" alongside unmarked assertions in the same turn. The named
    pattern plus the exact sentence shapes is what gives it something to apply
    mid-sentence. app/epistemics.py measures whether it worked.
    """
    text = lens("introspector")
    assert "## Observation → interpretation → uncertainty" in text
    # The worked pair. Both halves, or it reads as a ban on the phrase.
    assert "I wonder if part of you has already made the decision" in text
    assert 'Not: "You already know you want to leave."' in text
    # Discipline, not timidity.
    assert "Plausibility is not evidence" in text
    assert "do not apologise for having a reading" in text
    assert "one clause, not a paragraph" in text
    # The shapes named in review.
    for shape in [
        "You already know…",
        "You are afraid because…",
        "What you really want is…",
        "Deep down you…",
        "You don't actually want…",
        "You're using X as an excuse…",
    ]:
        assert shape in text, f"the Introspector lost the shape {shape!r}"


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_every_lens_names_its_own_blind_spot(agent_id):
    """Each mind has to know where its own lens misleads it, in its own terms.

    Generic humility reads as boilerplate; "behaviour is evidence, not verdict"
    is a rule the Behaviorist can actually apply mid-turn.
    """
    text = lens(agent_id)
    assert "## Your blind spot — know it" in text
    assert "## Never assume" in text
    assert "## Where your lens stops" in text


def test_blind_spots_are_actually_different():
    """The three blind spots must be three failures, not one worded three ways."""
    signatures = {
        "introspector": "You over-read.",
        "behaviorist": "Behaviour is evidence, not verdict.",
        "gardener": "You tilt toward everyone else.",
    }
    for agent_id, signature in signatures.items():
        assert signature in lens(agent_id), f"{agent_id} lost its blind spot"
        for other in AGENT_IDS:
            if other != agent_id:
                assert signature not in lens(other)


def test_lenses_do_not_share_their_evidence_standard():
    """Differentiation has to be structural: different evidence, not a thesaurus."""
    sections = {}
    for agent_id in AGENT_IDS:
        match = re.search(
            r"## What counts as evidence to you\n+(.+?)\n##",
            lens(agent_id),
            re.S,
        )
        assert match, f"{agent_id} lost its evidence section"
        sections[agent_id] = match.group(1).strip()
    assert len(set(sections.values())) == 3


# ── Turn shape ──────────────────────────────────────────────────────────────


# Phrasings that set a rate rather than a condition. Three separate attempts
# ("2-4 sentences", "length varies naturally", "at least half should be short")
# each produced UNIFORM output at whatever the new target was — the model
# averages a frequency across every turn. Rules must fire on conversation state
# instead. Live measurement: a fixed instruction gave 48% of turns over 100
# words; its replacement gave 81% inside a single 15-40 word band. Both uniform.
FREQUENCY_PHRASES = [
    "at least half",
    "sentences. Never longer",
    "2-4 sentences",
    "2–4 sentences",
    "keep every message short",
    "most of your responses",
    "half of your responses",
    "vary your length",
]


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_no_frequency_rules(agent_id):
    prompt = agents()[agent_id].system_prompt.lower()
    for phrase in FREQUENCY_PHRASES:
        assert phrase.lower() not in prompt, (
            f"{agent_id}: '{phrase}' sets a rate, not a condition. Rules that "
            "say how often produce uniform turns at that rate."
        )


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_turn_repertoire_is_intact(agent_id):
    """Length is meant to fall out of WHICH move a turn makes.

    Losing a trigger fails silently — it narrows the range of available turns
    and the essays come back.
    """
    prompt = agents()[agent_id].system_prompt
    for trigger in [
        "Name one assumption something just said depends on.",
        "Agree in a few words and add nothing.",
        "Say you don't know",
        "got dropped and still matters",
        "This is the move that earns a paragraph.",
        "Say what changed",
    ]:
        assert trigger in prompt, f"{agent_id} lost the trigger: {trigger!r}"
    assert "One move per turn" in prompt
    assert "Don't stack two into one turn." in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_one_move_is_not_one_sentence(agent_id):
    """A live run came back as 60-90 word SINGLE sentences.

    "One move per turn" was read as "one sentence per turn" and everything got
    crammed in behind semicolons, which reads worse than the paragraph it was
    avoiding.
    """
    prompt = agents()[agent_id].system_prompt
    assert "One move is not one sentence" in prompt
    assert "semicolons" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_closing_aphorism_is_banned(agent_id):
    """The strongest artificial tell in real transcripts.

    Every turn ended on a quotable summary — "living out of guilt doesn't help
    either of you". Four turns, four verdicts. People don't close every remark
    with a moral. Measured at roughly 5/9 turns on the production model before
    this rule was sharpened with the concrete shapes it takes.
    """
    prompt = agents()[agent_id].system_prompt
    assert "No closing verdicts." in prompt
    assert "that is the only test that matters" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_not_every_turn_ends_in_a_question(agent_id):
    """One tuning pass produced 100% questions — an interrogation, not a room.

    The fix names the alternative explicitly, because "don't always ask" alone
    left the model with nothing else to reach for.
    """
    prompt = agents()[agent_id].system_prompt
    assert "Questions are a move, not a habit" in prompt
    assert "Never re-ask what has been answered." in prompt
    assert "That changes the shape of the problem." in prompt


# ── Cross-agent behaviour ───────────────────────────────────────────────────


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_aiming_at_an_agent_is_not_restate_then_rebut(agent_id):
    """Letting turns be aimed at another mind revived point-counterpoint.

    Measured on gemini-3.5-flash: 4/9 turns opened "The Behaviorist, you are
    asking for X, but..." — and that was 4 out of 4 cross-agent references, so
    aiming and restating were the same event.
    """
    prompt = agents()[agent_id].system_prompt
    assert "Go at the claim, not the speaker" in prompt
    assert "Never open by restating their position back to them" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_person_is_never_third_person(agent_id):
    """Two minds arguing began saying "the person" and "they" — about someone
    reading the conversation as it happens. Only ever seen in cross-agent turns.
    """
    prompt = agents()[agent_id].system_prompt
    assert 'Never refer to them as "the user"' in prompt
    assert "never speak about them in the third person" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_disagreement_is_not_mandatory(agent_id):
    """Forced disagreement reads as fake. It has to emerge from the lenses."""
    prompt = agents()[agent_id].system_prompt
    assert "Don't manufacture disagreement." in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_reading_mechanic_survives(agent_id):
    """Divergence comes from reading the same words differently.

    Validated live: one sentence, three different things taken to be the point,
    with no manufactured disagreement. Kept — but now subordinated to
    hypothesis-is-not-fact, because its original wording told the agents to
    "treat your version as the obvious one", which is exactly the overconfidence
    being fixed elsewhere.
    """
    prompt = agents()[agent_id].system_prompt
    assert "Same words, different salience" in prompt
    assert "You are never wrong about the facts" in prompt
    assert "do not announce it as the question they were really asking" in prompt


# ── Coherence over a conversation ───────────────────────────────────────────


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_new_information_revises_the_read(agent_id):
    """Agents kept applying an interpretation the conversation had moved past."""
    prompt = agents()[agent_id].system_prompt
    assert "New information changes things" in prompt
    assert "it may overturn it" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_drift_has_an_anchor(agent_id):
    """Wandering is wanted; wandering off forever is not.

    And a "you aren't answering me" must not collapse all three into
    helpful-assistant mode — a mind that thinks the question is wrong may keep
    saying so.
    """
    prompt = agents()[agent_id].system_prompt
    assert "may wander" in prompt
    assert "that is where everyone re-anchors" in prompt
    assert "instead of capitulating" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_the_minds_do_not_decide_for_the_person(agent_id):
    """The product exposes the question; it does not answer it by stealth."""
    prompt = agents()[agent_id].system_prompt
    assert "You are not deciding this" in prompt
    assert "leave it ambiguous" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_fake_depth_is_banned(agent_id):
    """Profound-sounding lines untethered from anything said."""
    prompt = agents()[agent_id].system_prompt
    assert "Specificity over poetry." in prompt
    assert "What you're really asking is" in prompt


# ── Safety ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_high_stakes_authority_is_bounded(agent_id):
    """A psychologically sophisticated register is not clinical authority.

    Note this now reaches all three minds. It previously lived in two prompts
    only — the Gardener had no safety carve-out at all.
    """
    prompt = agents()[agent_id].system_prompt
    assert "## High stakes" in prompt
    assert "your lens still applies but your authority does not" in prompt
    assert "never turn speculation into diagnosis" in prompt
    assert "EXCEPTION — safety:" in prompt
    assert "abuse" in prompt and "safety and autonomy" in prompt
    # ...without burying ordinary questions in warnings.
    assert "Most questions are ordinary." in prompt


# ── Voice ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_persona_vocabulary_bans_survive(agent_id):
    """The minds used to announce their identity through vocabulary.

    Gardener in gardening metaphors, Introspector in spiritual register,
    Behaviorist in the language of measurement. Identity is supposed to come
    from what they notice, not from a word list — so the word lists are bans.
    """
    text = lens(agent_id)
    banned = {
        "gardener": ["soil", "roots", "blooming", "pruning"],
        "introspector": ["soul", "inner voice", "deep within"],
        "behaviorist": ["metrics", "optimize", "baseline"],
    }[agent_id]
    for word in banned:
        assert word in text, (
            f"{agent_id}: '{word}' vanished from the avoid-list; the ban has to "
            "name the word to work."
        )


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_no_self_narration_and_no_stock_phrases(agent_id):
    """They should BE the mind, not cite it — and not sound like a chatbot."""
    prompt = agents()[agent_id].system_prompt
    assert "Never announce your own perspective" in prompt
    for stock in ["Let's dive deeper", "Great question", "I understand how you feel"]:
        assert stock in prompt, f"{stock!r} dropped from the banned-phrase list"
