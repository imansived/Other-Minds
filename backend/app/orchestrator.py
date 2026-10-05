"""Turn-taking.

Ported from app/page.tsx. This logic used to run in the browser, which meant the
client decided who spoke next; it belongs on the server, so it lives here now.

Turn order is semi-random rather than strict rotation, so the exchange feels
like an organic group discussion. Consecutive turns MOSTLY pass to a different
agent, but ~1 in 4 turns the same agent speaks again. The models never choose
the order themselves.
"""

import random
import re

from app.agents.registry import AGENT_IDS, AGENT_NAMES
from app.config import settings
from app.schemas import AgentId, ChatMessage

# How a person names the mind they want to hear from. Both the display name and
# the bare word, because "introspector, what do you think?" is typed at least as
# often as "The Introspector" — and an optional "the" in front of either.
#
# The bare word does mean "my gardener quit last week" summons The Gardener.
# That is accepted deliberately: the cost is one mind answering a message it was
# going to be eligible for anyway, against the cost of missing the lowercase
# summons, which is the common form and the whole point of the feature.
_SUMMONS: dict[AgentId, re.Pattern[str]] = {
    agent_id: re.compile(
        rf"\b(?:the\s+)?{re.escape(name.removeprefix('The '))}\b", re.I
    )
    for agent_id, name in AGENT_NAMES.items()
}


def last_agent_speaker(transcript: list[ChatMessage]) -> AgentId | None:
    """The last agent (not the user) to have spoken, or None."""
    for m in reversed(transcript):
        if m.role != "user":
            return m.role  # type: ignore[return-value]
    return None


def summoned(transcript: list[ChatMessage]) -> AgentId | None:
    """The mind the person asked for by name, or None if they asked for no one.

    Only the final message counts, and only when the person is the one who just
    spoke. Once a mind has answered, the summons has been served — otherwise
    "hear another mind" would keep re-electing the same one forever, because the
    name is still sitting there in the transcript.

    Exactly one name summons. Naming two is a topic, not a request ("I think the
    Gardener and the Behaviorist are both missing something"), so the ordinary
    draw handles it rather than picking one of them arbitrarily.
    """
    if not transcript:
        return None
    last = transcript[-1]
    if last.role != "user":
        return None
    named = [a for a, pattern in _SUMMONS.items() if pattern.search(last.content)]
    return named[0] if len(named) == 1 else None


def choose_speaker(
    transcript: list[ChatMessage],
    *,
    allow_same: bool = True,
    rng: random.Random | None = None,
) -> AgentId:
    """Who speaks next: the mind asked for by name, otherwise the weighted draw.

    This is the entry point every client should use. Asking for a mind by name
    and getting a different one is the flaw it exists to close — the room was
    ignoring the one thing the person said unambiguously.

    A summons beats `allow_same`: naming a mind that just spoke is a request for
    more from that mind, not a mistake to correct.
    """
    return summoned(transcript) or pick_next_speaker(
        last_agent_speaker(transcript), allow_same=allow_same, rng=rng
    )


def pick_next_speaker(
    last: AgentId | None,
    *,
    allow_same: bool = True,
    rng: random.Random | None = None,
) -> AgentId:
    """Who speaks next, given who spoke last (None when no agent has yet).

    `allow_same` is what separates the two ways a turn gets asked for, which are
    not the same request even though they run the same code.

    When the person writes a reply, the room carries on and whoever is mid-
    thought may well keep it — that is the double turn, and it is wanted.

    When the person presses "hear another mind", they have asked for someone
    else, in those words. Letting the draw return the same agent one time in
    four breaks the only promise the button makes, and it is visible: in the
    conversation that prompted this, The Introspector answered, was asked for
    another mind, and answered again. Nothing in the UI explained why.

    `rng` is injectable so tests can make the draw deterministic.
    """
    r = rng or random
    others = [a for a in AGENT_IDS if a != last]
    if last is None:
        return r.choice(AGENT_IDS)
    if allow_same and r.random() < settings.double_turn_chance:
        return last
    # A one-agent registry would leave nothing to switch to. Repeating is then
    # the only answer there is, and is better than raising.
    return r.choice(others or [last])
