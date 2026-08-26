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
    rng: random.Random | None = None,
) -> AgentId:
    """Who speaks next, given who spoke last (None when no agent has yet).

    `rng` is injectable so tests can make the draw deterministic.
    """
    r = rng or random
    if last is None:
        return r.choice(AGENT_IDS)
    if r.random() < settings.double_turn_chance:
        return last
    return r.choice([a for a in AGENT_IDS if a != last])
