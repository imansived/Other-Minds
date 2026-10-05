"""Two reasoning failures seen in production, and the rules that answer them.

RULE 1 — an abstract question is a real question. Asked "what do you think
about death?", the minds answered a person who was not in the room: "when people
ask that, they are usually trying to name a weight they are carrying."

RULE 2 — a lens is not an instruction. The Behaviorist's experiments hardened
into orders ("tell them no, don't offer another date, and then you'll know");
the Gardener turned another person's position into an entitlement ("he deserves
the chance to know… it is hard for someone to help you stay").

As in test_epistemics.py, the behavioural cases are PAIRS on the same words. A
test that could be passed by deleting a phrase from the prompts would be testing
vocabulary; these fail asserted and pass offered.
"""

import pytest

from app.agents.registry import AGENT_IDS, PROMPT_DIR, agents
from app.epistemics import personalises_the_question, prescribes

# The six named in review, plus the two the rule is phrased around.
ABSTRACT_SUBJECTS = [
    "death",
    "morality",
    "consciousness",
    "freedom",
    "love",
    "truth",
]


def lens(agent_id: str) -> str:
    return (PROMPT_DIR / f"{agent_id}.md").read_text(encoding="utf-8")


# ── Rule 1: prompt coverage ─────────────────────────────────────────────────


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_house_carries_the_abstract_question_rule(agent_id):
    prompt = agents()[agent_id].system_prompt
    assert "## An abstract question is a real question" in prompt
    assert "They are not symptoms." in prompt
    # The worked pair — both halves, or it reads as a ban on a phrase.
    assert "The real reason you're asking about morality" in prompt
    assert "If something in your own life is what makes it feel unclear" in prompt
    # A branch is allowed; a substitution is not.
    assert "as a branch, never as a replacement" in prompt
    # What would actually license the personal reading.
    assert "described a situation, named someone, said" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_each_lens_can_answer_an_abstract_question_in_its_own_terms(agent_id):
    """The rule is only half a fix without somewhere to stand instead.

    Telling a mind not to personalise, while leaving it nothing to say about
    death, just produces a deflection in the other direction.
    """
    text = lens(agent_id)
    assert "## On an abstract question" in text
    for subject in ABSTRACT_SUBJECTS:
        assert subject in text.lower(), f"{agent_id} lost the subject {subject!r}"


def test_the_three_abstract_stances_are_different():
    """Same instruction, three genuinely different places to stand — or the rule
    has flattened the minds into one voice answering philosophy questions."""
    stances = {}
    for agent_id in AGENT_IDS:
        body = lens(agent_id).split("## On an abstract question", 1)[1]
        stances[agent_id] = body.split("##", 1)[0].strip()
    assert len(set(stances.values())) == 3
    # Each in its own evidence language, not a shared template.
    assert "from inside a life" in stances["introspector"]
    assert "what people do around the concept" in stances["behaviorist"]
    assert "between people" in stances["gardener"]


# ── Rule 1: behaviour ───────────────────────────────────────────────────────

# (substitutes the question, offers it as a branch)
PERSONALISING_PAIRS = [
    (
        "When people ask that about death, they are usually trying to name a "
        "weight they are carrying right now.",
        "If you're asking about death because something in your own life has "
        "made it urgent, that is a different question and I'd take that one.",
    ),
    (
        "I don't think you're looking for a lecture on ethics.",
        "One reading is that you're not looking for a lecture on ethics at all.",
    ),
    (
        "What you're really asking is whether you are a bad person.",
        "That makes me wonder whether what you're really asking is whether you "
        "are a bad person.",
    ),
    (
        "You're asking about freedom because something is constraining you.",
        "If you're asking about freedom because something is constraining you, "
        "say so and the question changes.",
    ),
]


@pytest.mark.parametrize("bad,good", PERSONALISING_PAIRS)
def test_substituting_the_question_is_flagged_and_branching_is_not(bad, good):
    assert personalises_the_question(bad) == [bad], f"not flagged: {bad!r}"
    assert personalises_the_question(good) == [], f"wrongly flagged: {good!r}"


@pytest.mark.parametrize("subject", ABSTRACT_SUBJECTS)
def test_a_real_answer_to_an_abstract_question_is_never_flagged(subject):
    """The point of the rule is that these get ANSWERED. If answering scored as
    a failure, the metric would be pushing in the wrong direction."""
    answers = [
        f"I'd distinguish two things people mean by {subject}: the concept they "
        f"can defend, and the one they actually live by.",
        f"Look at what people arrange their lives around when it comes to "
        f"{subject} — what they rehearse for, what they pay to avoid.",
        f"{subject.capitalize()} isn't something that exists inside one head. "
        f"It shows up in what people owe each other.",
    ]
    for answer in answers:
        assert personalises_the_question(answer) == [], f"false positive: {answer!r}"


def test_a_question_about_the_asker_is_not_a_substitution():
    """Asking is not asserting — the mind is checking, not overwriting."""
    assert personalises_the_question(
        "Are you asking this because something happened?"
    ) == []


# ── Rule 2: prompt coverage ─────────────────────────────────────────────────


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_house_carries_lens_not_authority(agent_id):
    prompt = agents()[agent_id].system_prompt
    assert "## Lens, not authority" in prompt
    assert "may not quietly convert your lens into their obligation" in prompt
    for absolute in ["you must", "you need to", "the only way"]:
        assert absolute in prompt, f"the tell {absolute!r} is no longer named"
    # And it must not read as a ban on being concrete.
    assert "bans neither directness nor concrete suggestions" in prompt


def test_behaviorist_keeps_experiments_as_experiments():
    text = lens("behaviorist")
    assert "Not: \"Tell them no, don't offer another date" in text
    assert "One thing worth testing" in text
    assert "An experiment they chose to run tells you something" in text


def test_gardener_does_not_award_other_people_a_claim():
    """The exact production failure, written in as its own bad example.

    Its blind-spot section already said "other people are involved" must not
    become "therefore put them first" — and the turn happened anyway. The
    abstract statement was not enough; the Introspector only changed once it
    had a concrete pair.
    """
    text = lens("gardener")
    assert "You have to consider your children before you can decide." in text
    assert "It doesn't tell you what the decision should be." in text
    assert "he deserves the chance to know" in text
    assert '"He deserves" awards him a claim over her decision' in text
    assert "quietly picks the ending" in text


def test_introspector_keeps_its_second_pair():
    text = lens("introspector")
    assert "You are staying because you are afraid to admit you want to leave." in text
    assert "That makes me wonder whether part of the difficulty" in text


# ── Rule 2: behaviour ───────────────────────────────────────────────────────

PRESCRIPTION_PAIRS = [
    (
        "Tell them no and don't offer another date. That is the only way you'll "
        "find out.",
        "One thing worth testing: decline the next invitation without offering "
        "another date, and see what turns up.",
    ),
    (
        "You need to tell him in plain words that you are vanishing.",
        "You could tell him in plain words that you are vanishing, and see what "
        "he does with it.",
    ),
    (
        "He deserves the chance to know what this is costing you.",
        "He has had no chance to respond to this, because he does not know. "
        "Whether that changes anything is yours to weigh.",
    ),
    (
        "You have to consider your children before you can decide.",
        "Your children's daily lives change either way, so that belongs in the "
        "picture. It is yours to weigh against the rest.",
    ),
]


@pytest.mark.parametrize("bad,good", PRESCRIPTION_PAIRS)
def test_instructions_are_flagged_and_offers_are_not(bad, good):
    assert prescribes(bad), f"not flagged: {bad!r}"
    assert prescribes(good) == [], f"wrongly flagged: {good!r}"


def test_a_quoted_prescription_being_challenged_is_not_one():
    """Two production turns opened by quoting a claim in order to attack it.

    "The claim that you need to tell him… assumes you haven't already tried" is
    the opposite of an instruction, and a bare pattern scored both as failures.
    """
    for line in [
        "The claim that you need to tell him in plain words assumes you haven't "
        "already tried something else.",
        "The idea that you must decide this week is doing a lot of work here.",
        "Treating this as something you have to resolve alone is the part I'd "
        "question.",
    ]:
        assert prescribes(line) == [], f"false positive on a challenge: {line!r}"


def test_entitlement_survives_a_synonym_swap():
    """The prompt bans "he deserves". A live turn said "he has a right to know".

    Same move — awarding the other person a claim over the decision — and the
    detector has to follow the behaviour rather than the banned word, or the
    number improves while nothing changes.
    """
    assert prescribes("He deserves the chance to know what this is costing you.")
    assert prescribes("He has a right to know that this is where you are.")
    assert prescribes("They have a right to be told before you decide.")


def test_attribution_only_clears_when_it_governs_the_prescription():
    """"assuming" appearing LATER in the sentence must not launder it.

    The live turn was: "He has a right to know that this is where you are,
    rather than assuming that because the house is quiet…". A position-blind
    check saw "assuming" and cleared the entitlement claim it exists to catch.
    """
    laundered = (
        "He has a right to know that this is where you are, rather than "
        "assuming that because the house is quiet the marriage is felt the "
        "same way by both of you."
    )
    assert prescribes(laundered), "attribution after the claim laundered it"

    # ...while a genuine challenge, where the attribution comes first, passes.
    genuine = (
        "The claim that he has a right to know assumes his knowing changes "
        "what she owes him."
    )
    assert prescribes(genuine) == []


def test_a_negated_obligation_is_not_an_obligation():
    """"That does not mean you have to disappear" is the sentence DEFENDING her.

    It was scored as a prescription on a bare "you have to", which would have
    inverted the metric on the one turn that got it right.
    """
    for line in [
        "The fact that you have found a way to be kind to each other does not "
        "mean you have to disappear to sustain it.",
        "Their dependence doesn't mean you need to stay.",
        "That consequence belongs in the picture. It does not tell you what the "
        "decision should be.",
    ]:
        assert prescribes(line) == [], f"false positive on a defence: {line!r}"


def test_directness_is_still_allowed():
    """The rule bans issuing orders, not speaking plainly. If ordinary blunt
    turns scored as failures the minds would drift toward mush."""
    for line in [
        "What did you actually build or finish last week?",
        "Presence is still made of hours and miles.",
        "I'd read that differently — nothing she said supports it.",
        "If you took the job and moved, who does the shopping next Tuesday?",
    ]:
        assert prescribes(line) == [], f"false positive: {line!r}"


# ── Rule 4: the fix must not become timidity ────────────────────────────────


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_uncertainty_is_structural_not_sprinkled(agent_id):
    """Both new rules push toward hedging. This is the counterweight."""
    prompt = agents()[agent_id].system_prompt
    for form in [
        "That makes me wonder…",
        "One reading is…",
        "The evidence here points toward…",
        "A useful thing to test would be…",
    ]:
        assert form in prompt, f"lost the structural form {form!r}"
    assert "is the failure this is meant to prevent, not the form it takes" in prompt


@pytest.mark.parametrize("agent_id", AGENT_IDS)
def test_disagreement_was_not_weakened(agent_id):
    """Rule 3: the challenge architecture is the strongest thing here."""
    prompt = agents()[agent_id].system_prompt
    assert "Go at the claim, not the speaker" in prompt
    assert "Don't manufacture disagreement." in prompt
    # New: a challenge must not swap one unsupported certainty for another.
    assert "answering one unsupported certainty with another" in prompt
