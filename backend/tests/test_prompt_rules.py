"""Guards on the prompt rules that were arrived at by trial and error.

Each assertion here corresponds to a failure we actually observed in generated
conversations, so the comments record WHY the rule exists — otherwise the
obvious "cleanup" is to put the deleted instruction back.

Nothing here calls the API. These check the prompt text itself; whether the
model obeys is a separate question that only a live run answers.
"""

import re

import pytest

from app.agents.registry import AGENT_IDS, agents

# Phrasings that set a rate rather than a condition. Three separate attempts
# ("2-4 sentences", "length varies naturally", "at least half should be short")
# each produced UNIFORM output at whatever the new target was — the model
# averages a frequency across every turn. Rules must fire on transcript state
# instead, so that variation comes from the conversation rather than from the
# model trying to hit a quota.
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

# One move per turn, expressed as conditions.
REQUIRED_TRIGGERS = [
    "only holds if something is true that the person never told you",
    "have nothing to add",
    "carrying more weight than everything around it",
    "You don't know. Say that.",
    "got dropped and still matters",
    "this is the move that earns a paragraph",
    "aimed at one of the others",
    "changes your read",
]


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_no_frequency_rules(agent_id):
    """See FREQUENCY_PHRASES. A rate is the one thing that reliably backfires."""
    prompt = agents()[agent_id].system_prompt.lower()
    for phrase in FREQUENCY_PHRASES:
        assert phrase.lower() not in prompt, (
            f"{agent_id}: '{phrase}' sets a rate, not a condition. Rules that "
            "specify how often produce uniform turns at that rate."
        )


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_turn_repertoire_is_intact(agent_id):
    """Length is meant to fall out of WHICH move a turn makes.

    Losing a trigger doesn't fail loudly — it just quietly narrows the range of
    turns the agent can take, and the essays come back.
    """
    prompt = agents()[agent_id].system_prompt
    for trigger in REQUIRED_TRIGGERS:
        assert trigger in prompt, f"{agent_id} lost the trigger: {trigger!r}"
    assert "One move per turn." in prompt
    assert "Do not stack two of these into one turn." in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_closing_aphorism_is_banned(agent_id):
    """The strongest artificial tell we saw in real transcripts.

    Every turn ended on a quotable summary line — "living out of guilt doesn't
    help either of you", "it's just changing the location of the friction".
    Four turns, four verdicts. People don't close every remark with a moral.
    """
    prompt = agents()[agent_id].system_prompt
    assert "Never end on a line that sums up your turn." in prompt
    assert "no sentence that could be lifted out and quoted on its own" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_phrase_borrowing_is_banned(agent_id):
    """Three minds reached for "packing the boxes" in the same exchange.

    That is pattern-matching on the transcript, not independent interpretation,
    and it makes the agents read as one voice in three costumes.
    """
    prompt = agents()[agent_id].system_prompt
    assert "Do not reuse another agent's phrasing or imagery." in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_reading_mechanic_is_present(agent_id):
    """Divergence has to come from reading the same words differently.

    If the agents share a reading and only differ in advice, they converge —
    and then disagreement has to be manufactured, which reads as fake. Note the
    hard line: salience may differ, facts may NOT.
    """
    prompt = agents()[agent_id].system_prompt
    assert "Reading what's said:" in prompt
    assert "supports more than one reading" in prompt
    assert "You are never wrong about the facts." in prompt
    assert "is not the one they are actually facing" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_one_move_is_not_one_sentence(agent_id):
    """First live run came back as 60-90 word SINGLE sentences.

    "One move per turn" was read as "one sentence per turn", and everything got
    crammed in behind semicolons — which reads worse than the paragraph it was
    avoiding.
    """
    prompt = agents()[agent_id].system_prompt
    assert "One move does not mean one sentence." in prompt
    assert "semicolons" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_aiming_at_an_agent_is_not_restate_then_rebut(agent_id):
    """Letting turns be aimed at another agent revived point-counterpoint.

    5 of 9 turns opened "The Behaviorist, you're asking for data, but...".
    Aiming a turn is fine; prefacing it with their position is not.
    """
    prompt = agents()[agent_id].system_prompt
    assert "do not open by restating their position back to them" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_person_is_never_third_person(agent_id):
    """Two agents arguing began saying "the person" and "they" — about someone
    who is reading the conversation as it happens."""
    prompt = agents()[agent_id].system_prompt
    assert "the person is still in the room and still reading" in prompt
    assert "Never refer to them in the third person" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_drift_has_an_anchor(agent_id):
    """Wandering is wanted; wandering off forever is not.

    The person's next message is the tether. And a "you aren't answering me"
    must not collapse all three into helpful-assistant mode — an agent that
    thinks the question is wrong is allowed to keep saying so.
    """
    prompt = agents()[agent_id].system_prompt
    assert "allowed to wander" in prompt
    assert "where everyone re-anchors" in prompt
    assert "instead of capitulating" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_consecutive_turn_rule_survives(agent_id):
    """An agent given two turns in a row used to reword its own last point."""
    prompt = agents()[agent_id].system_prompt
    assert "immediately preceding turn" in prompt
    assert "do NOT restate your last point in different words" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_persona_vocabulary_bans_survive(agent_id):
    """The agents used to announce their identity through vocabulary.

    Gardener in gardening metaphors, Introspector in spiritual register,
    Behaviorist in the language of measurement. Identity is supposed to come
    from what they notice, not from a word list.
    """
    prompt = agents()[agent_id].system_prompt
    assert "Voice — important:" in prompt
    banned = {
        "gardener": ["soil", "roots", "blooming", "pruning"],
        "introspector": ["soul", "inner voice", "deep within"],
        "behaviorist": ["metrics", "optimize", "baseline"],
    }[agent_id]
    for word in banned:
        assert word in prompt, (
            f"{agent_id}: '{word}' vanished from the avoid-list; the ban has to "
            "name the word to work."
        )


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_no_self_narration(agent_id):
    """"As the Behaviorist, I'd say..." — they should BE the mind, not cite it."""
    prompt = agents()[agent_id].system_prompt
    assert "Never announce or explain your own perspective" in prompt


def test_agents_do_not_share_a_reading_example():
    """Each agent illustrates the mechanic with what IT would notice.

    Identical examples across the three would teach them the same reading,
    which is the opposite of the point.
    """
    examples = {}
    for agent_id in AGENT_IDS:
        prompt = agents()[agent_id].system_prompt
        match = re.search(r"what stands out to you is (.+?)\n", prompt)
        assert match, f"{agent_id} lost its reading example"
        examples[agent_id] = match.group(1)
    assert len(set(examples.values())) == 3, f"agents share an example: {examples}"
