"""Does a claim about someone's inner life admit that it is a claim?

The Introspector's whole value is reading what a person has not said outright.
Its whole failure mode is promoting that reading into a fact because it sounded
psychologically plausible — and plausibility is not evidence. A well-made
sentence is the easiest thing in the world to mistake for a true one:

    "You already know you want to leave."
    "The fear of resenting them is already a form of resentment."

Neither is checkable, and both are stated as established. The fix is not to ban
the sentence. It is to require the third beat:

    observation → interpretation → uncertainty

    "You keep returning to the idea of leaving. I wonder if part of you has
     already made the decision, while another part is afraid of what follows."

Same reading, same sharpness, honest about its own standing. So this module
does not look for phrases — it looks for a claim about an inner state that
carries no marker saying whose claim it is. The identical phrase passes or fails
depending on whether the marker is there, which is the behaviour being
protected rather than the vocabulary.

No pandas here on purpose: analytics.py imports this for the corpus metric, and
the live scenario harness imports it too, where a dataframe stack would be dead
weight.
"""

import re

# Claims about what someone privately knows, wants, or fears. Deliberately
# NARROW, for the same reason VERDICT_CLOSERS in analytics.py is narrow: a loose
# pattern ("you feel", "you want") fires on every sentence where a mind repeats
# back what the person already told it, which is not mind-reading at all and
# would bury the signal.
#
# These are the shapes that assert privileged access — a state the person did
# not report, which no one outside them can check.
MIND_READING = (
    r"\byou already know\b",
    r"\bdeep down,?\s+you\b",
    r"\bwhat you really (?:want|mean|feel|need|think)\b",
    r"\byou really (?:want|mean|feel|need)\b",
    r"\bwhat you(?:'re| are) really (?:asking|doing|saying|afraid)\b",
    r"\byou(?:'re| are)n?o?t? actually (?:want|believe|feel|afraid)",
    r"\byou don'?t actually (?:want|believe|feel|know)\b",
    r"\byou actually (?:want|believe|feel|know)\b",
    r"\byou(?:'re| are) (?:afraid|scared|terrified|angry|worried) (?:because|of that|that)\b",
    r"\byou(?:'re| are) using\b[^.!?]*\bas an excuse\b",
    r"\bthe real reason (?:you|that you)\b",
    r"\byour real (?:fear|reason|motive)\b",
)

# Markers that hand the claim back as the speaker's own reading. A question
# counts too, and is handled separately — asking is never asserting.
#
# "if" and "unless" are left out: they clear far too much ("you already know
# what you want, if you are honest with yourself" is not hedged, it is a dare).
EPISTEMIC_MARKERS = (
    # Not just "I wonder": the house style recommends "That makes me wonder…"
    # as a preferred structural hedge, and a pattern anchored to "i" scored that
    # exact phrasing as an unowned assertion — penalising the form being asked
    # for. "no wonder" is not swept up, since that has no pronoun before it.
    r"\b(?:i|me|one)\s+wonder(?:s|ing)?\b",
    r"\bi suspect\b",
    r"\bi(?:'m| am) guessing\b",
    r"\bi could be wrong\b",
    r"\bi may be wrong\b",
    # The bare modals, which is how most real hedging is actually done:
    # "you may have already decided", "that could be what the word is doing".
    # Listing only "may be"/"could be" missed the commonest form of all.
    r"\bmight\b",
    r"\bmaybe\b",
    r"\bmay\b",
    r"\bcould\b",
    r"\bperhaps\b",
    r"\bpossibly\b",
    r"\bone possibility\b",
    # Named in the house style as preferred structural forms, so they belong in
    # the general marker set rather than only in the abstract-question one.
    r"\bone reading\b",
    r"\bpoints toward\b",
    r"\bi would distinguish\b",
    r"\bcould be\b",
    r"\bit seems\b",
    r"\bseems? (?:to|like)\b",
    r"\bsounds? like\b",
    r"\bsuggests?\b",
    r"\bmy read\b",
    r"\bmy guess\b",
    r"\bthat(?:'s| is) a guess\b",
    r"\bfrom here\b",
    r"\bi can'?t know\b",
    r"\bnot something i (?:can|could) know\b",
)

# Reporting back what the person actually said is an observation, however
# confidently it is phrased — "you said you already know" is quoting them.
QUOTING_THE_PERSON = (
    r"\byou (?:said|told|wrote|mentioned|called|described|put it)\b",
    r"\byou keep (?:saying|calling|describing|coming back to|returning to)\b",
    r"\byour own words?\b",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Gemini writes curly apostrophes, and every contraction above is spelled with
# a straight one. Without this the detector silently passes exactly the turns it
# exists to catch: "You’re afraid that…" scored clean while the identical
# sentence typed with ' was flagged. Found by reading a transcript the metric
# had already called 0/15.
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})


def normalise(text: str) -> str:
    return str(text).translate(_APOSTROPHES)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(normalise(text).strip()) if s.strip()]


def _any(patterns: tuple[str, ...], sentence: str) -> bool:
    # Normalised here as well as in sentences(), so the predicates are safe to
    # call directly on raw model output.
    text = normalise(sentence)
    return any(re.search(p, text, re.I) for p in patterns)


def asserts_inner_state(sentence: str) -> bool:
    """Does this sentence claim to know something the person did not report?"""
    return _any(MIND_READING, sentence)


def is_marked_as_interpretation(sentence: str) -> bool:
    """Does it say, in any form, that this is a reading rather than a finding?"""
    return sentence.rstrip().endswith("?") or _any(EPISTEMIC_MARKERS, sentence)


def unmarked_mind_reading(text: str) -> list[str]:
    """The sentences that claim privileged access without owning the claim.

    Empty list is the passing result. Returns the offending sentences rather
    than a count so a failure can be read, not just tallied.
    """
    flagged = []
    for sentence in sentences(text):
        if not asserts_inner_state(sentence):
            continue
        if _any(QUOTING_THE_PERSON, sentence):
            continue
        if is_marked_as_interpretation(sentence):
            continue
        flagged.append(sentence)
    return flagged


# ── Rule 1: an abstract question is a real question ─────────────────────────
#
# Asked "what do you think about death?", the minds were answering a person who
# was not in the room: "when people ask that, they are usually trying to name a
# weight they are carrying". That does not interpret the question, it replaces
# it — and the substitute is invented.
#
# A personal reading is allowed as a BRANCH ("if something in your own life is
# what makes this unclear, that's a different question"). It is not allowed as a
# substitution. So, as with mind-reading, this measures standing rather than
# vocabulary: the same sentence passes conditionally and fails asserted.
PERSONALISES = (
    r"\bwhen people ask (?:that|this)\b",
    r"\bpeople (?:who|that) ask (?:that|this)\b",
    r"\b(?:questions|people) like (?:this|that) (?:usually|always|generally)\b",
    r"\bnobody asks (?:this|that)\b",
    r"\bthe real reason you(?:'re| are) asking\b",
    r"\byou(?:'re| are) really asking\b",
    r"\bwhat you(?:'re| are) (?:really|actually) asking\b",
    r"\byou would ?n'?t be asking\b",
    r"\byou(?:'re| are) not (?:really )?asking about\b",
    r"\byou(?:'re| are) asking (?:this|that|about \w+) because\b",
    r"\bi don'?t think you(?:'re| are) (?:really )?(?:asking|after|looking for)\b",
)

# Conditional framing is the sanctioned form here, so unlike the mind-reading
# markers this set DOES accept "if". "If you're asking because something in your
# life feels unclear" offers a branch; it does not overwrite the question.
BRANCH_MARKERS = EPISTEMIC_MARKERS + (
    r"^if\b",
    r"\bif you(?:'re| are) asking\b",
    r"\bif that(?:'s| is) what\b",
    r"\btaken philosophically\b",
    r"\beither way\b",
    r"\bthat would be a different question\b",
)


def personalises_the_question(text: str) -> list[str]:
    """Sentences that swap the asked question for an invented personal one.

    Empty list passes. A branch offered conditionally is not a swap.
    """
    flagged = []
    for sentence in sentences(text):
        if not _any(PERSONALISES, sentence):
            continue
        if sentence.rstrip().endswith("?") or _any(BRANCH_MARKERS, sentence):
            continue
        flagged.append(sentence)
    return flagged


# ── Rule 2: a lens, not an instruction ──────────────────────────────────────
#
# The Behaviorist's experiments are the best thing it does, right up to the
# point where they stop being experiments: "tell them no, don't offer another
# date, and then you'll know. That is the only way to find out." The lens has
# become the person's week.
PRESCRIPTIVE = (
    r"\byou must\b",
    r"\byou need to\b",
    r"\byou have to\b",
    r"\byou(?:'ve| have) got to\b",
    r"\bthe only way (?:you|to|forward)\b",
    r"\bthat is the only way\b",
    r"\bstop (?:hiding|pretending|telling yourself|making excuses|avoiding)\b",
    r"\bdo (?:this|that|it) and (?:then )?you(?:'ll| will)\b",
    r"\byou owe (?:it |them|him|her)\b",
    r"\bhe deserves\b",
    r"\bshe deserves\b",
    r"\bthey deserve\b",
    # Same move, different word. The prompt bans "he deserves"; a live turn came
    # back with "he has a right to know that this is where you are", which
    # awards the other person exactly the same claim over the decision.
    r"\b(?:he|she|they) (?:has|have) a right to\b",
)

# "That does not mean you have to disappear" is the OPPOSITE of an instruction —
# it is the sentence defending the person's autonomy. A bare match on "you have
# to" scored it as a prescription, which would have inverted the metric on the
# one turn that got it right.
NEGATED = (
    r"\b(?:does|do|did) ?n'?t (?:mean|require|oblige)\b",
    r"\bdoes not (?:mean|require|oblige)\b",
    r"\bnothing says\b",
    r"\bno one (?:says|is saying)\b",
    r"\bthat (?:does|doesn'?t) ?n?o?t? (?:tell|settle|decide)\b",
)

# The same words, offered rather than issued.
OFFERED = (
    r"\byou could\b",
    r"\byou might\b",
    r"\bworth testing\b",
    r"\bone thing worth\b",
    r"\bone useful\b",
    r"\ba useful thing\b",
    r"\bif you wanted to\b",
    r"\bone experiment\b",
    r"\bwould be to test\b",
    r"\bis yours to\b",
    r"\byour call\b",
)

# A prescription being QUOTED in order to be challenged is not a prescription.
# Two live turns opened "The claim that you need to tell him… assumes…", which a
# bare pattern scores as an order when it is the opposite of one.
ATTRIBUTED = (
    r"\bthe claim that\b",
    r"\bthe idea that\b",
    r"\bassumes?\b",
    r"\bassuming\b",
    r"\btreat(?:s|ing|ed)? (?:this|that|your|it)\b",
    r"\bsaying (?:that )?you\b",
)


def _earliest(patterns: tuple[str, ...], sentence: str) -> int | None:
    """Where the first of these patterns matches, or None."""
    hits = [m.start() for p in patterns
            if (m := re.search(p, normalise(sentence), re.I))]
    return min(hits) if hits else None


def prescribes(text: str) -> list[str]:
    """Sentences where a lens has hardened into an instruction.

    Offers pass. Negated obligations pass. A prescription being quoted in order
    to be challenged passes — but only when the attribution actually GOVERNS it,
    which means appearing before it.

    That last point is not pedantry. "He has a right to know this, rather than
    assuming the marriage is felt the same way by both of you" contains
    "assuming", and a position-blind check cleared the entitlement claim it was
    supposed to catch.
    """
    flagged = []
    for sentence in sentences(text):
        at = _earliest(PRESCRIPTIVE, sentence)
        if at is None or sentence.rstrip().endswith("?"):
            continue
        if _any(OFFERED, sentence) or _any(NEGATED, sentence):
            continue
        attributed = _earliest(ATTRIBUTED, sentence)
        if attributed is not None and attributed < at:
            continue
        flagged.append(sentence)
    return flagged


def mind_reading_share(texts) -> float:
    """Share of turns carrying at least one unmarked claim about an inner state."""
    texts = list(texts)
    if not texts:
        return 0.0
    return sum(1 for t in texts if unmarked_mind_reading(t)) / len(texts)


# Rules 1 and 2 shipped with tests (test_abstract_and_authority.py) but no
# standing measurement: nothing in app/ ever called personalises_the_question
# or prescribes outside a test or a scratch script, so neither reasoning fix
# has a number attached to it in the corpus. These give analytics.chat_feel
# the same "share of turns" shape mind_reading_share already has.
def personalises_share(texts) -> float:
    """Share of turns that swap an asked question for an invented one."""
    texts = list(texts)
    if not texts:
        return 0.0
    return sum(1 for t in texts if personalises_the_question(t)) / len(texts)


def prescribes_share(texts) -> float:
    """Share of turns where a lens hardened into an instruction."""
    texts = list(texts)
    if not texts:
        return 0.0
    return sum(1 for t in texts if prescribes(t)) / len(texts)

