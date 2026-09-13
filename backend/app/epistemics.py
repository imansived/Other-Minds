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
    r"\bi wonder\b",
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


def mind_reading_share(texts) -> float:
    """Share of turns carrying at least one unmarked claim about an inner state."""
    texts = list(texts)
    if not texts:
        return 0.0
    return sum(1 for t in texts if unmarked_mind_reading(t)) / len(texts)
