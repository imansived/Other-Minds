"""Turn-taking.

Ported from app/page.tsx. This logic used to run in the browser, which meant the
client decided who spoke next; it belongs on the server, so it lives here now.

Turn order is semi-random rather than strict rotation, so the exchange feels
like an organic group discussion. Consecutive turns MOSTLY pass to a different
agent, but ~1 in 4 turns the same agent speaks again. The models never choose
the order themselves.
"""

import random

from app.agents.registry import AGENT_IDS
from app.config import settings
from app.schemas import AgentId, ChatMessage


def last_agent_speaker(transcript: list[ChatMessage]) -> AgentId | None:
    """The last agent (not the user) to have spoken, or None."""
    for m in reversed(transcript):
        if m.role != "user":
            return m.role  # type: ignore[return-value]
    return None


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
