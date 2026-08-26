"""Agent definitions.

The system prompts are the product. They live as .md files next to this module
and were extracted verbatim from app/lib/agents.ts — byte-for-byte, verified as
exact substrings of the original. Edit the .md files, never a copy.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.schemas import AgentId, ChatMessage

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

# Display names, used both in the prompt envelope and when rendering the
# transcript. These strings appear inside the prompts themselves, so they are
# not cosmetic — changing one silently breaks the agents' references to
# each other.
AGENT_NAMES: dict[AgentId, str] = {
    "introspector": "The Introspector",
    "behaviorist": "The Behaviorist",
    "gardener": "The Gardener",
}

# Turn order is drawn from this list; order here is not significant.
AGENT_IDS: list[AgentId] = ["introspector", "behaviorist", "gardener"]


@dataclass(frozen=True)
class AgentConfig:
    id: AgentId
    name: str
    system_prompt: str


@lru_cache(maxsize=1)
def agents() -> dict[AgentId, AgentConfig]:
    """Load and cache the agent registry, prompts included."""
    registry: dict[AgentId, AgentConfig] = {}
    for agent_id in AGENT_IDS:
        path = PROMPT_DIR / f"{agent_id}.md"
        if not path.is_file():
            raise FileNotFoundError(f"Missing system prompt for {agent_id}: {path}")
        registry[agent_id] = AgentConfig(
            id=agent_id,
            name=AGENT_NAMES[agent_id],
            system_prompt=path.read_text(encoding="utf-8"),
        )
    return registry


def get_agent(agent_id: str) -> AgentConfig | None:
    return agents().get(agent_id)  # type: ignore[arg-type]


def render_transcript(transcript: list[ChatMessage]) -> str:
    """Render the visible transcript as plain-text conversation history.

    Each agent only ever sees what was said out loud. Port of renderTranscript
    in app/lib/agents.ts — the blank-line separator and "Name: content" shape
    are load-bearing, since the prompts assume this layout.
    """
    lines = []
    for m in transcript:
        speaker = "User" if m.role == "user" else AGENT_NAMES[m.role]
        lines.append(f"{speaker}: {m.content}")
    return "\n\n".join(lines)
