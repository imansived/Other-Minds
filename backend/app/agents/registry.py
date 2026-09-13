"""Agent definitions.

The system prompts are the product. They live as .md files next to this module.

A prompt is assembled from two pieces, and the split is the point:

  <agent>.md   the LENS — worldview, what this mind notices, what it accepts as
               evidence, what it values, its blind spot, what it may never
               assume, and its own voice. Everything that makes it this mind
               rather than one of the others.

  _house.md    the HOUSE STYLE — how a turn is shaped, hypothesis vs fact,
               questions, challenging another mind, safety. Everything that is
               true of all three.

They used to be one file each, which meant the house rules existed in triplicate
and every edit had to be made three times or silently drift. It also made each
prompt long enough that the model started dropping rules: fixing one behaviour
reliably broke another that had been holding. One copy, loaded once, is both the
maintenance fix and the reason each mind's own section is now short enough to
carry weight.

Adding a fourth mind is now a lens file plus an entry in AGENT_NAMES.
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


HOUSE_PATH = PROMPT_DIR / "_house.md"

# Filled in from AGENT_NAMES rather than written out in the prose, so a fourth
# mind does not leave three prompts quietly claiming there are three.
ALL_NAMES_TOKEN = "__ALL_NAMES__"


def _join_names(names: list[str]) -> str:
    """"A, B and C" — Oxford-less, which is how the prompts already read."""
    if len(names) <= 1:
        return names[0] if names else ""
    return f"{', '.join(names[:-1])} and {names[-1]}"


def compose_prompt(agent_id: AgentId, lens: str, house: str) -> str:
    """Lens first, then the house style.

    Order matters: the lens is what distinguishes this mind, and putting it
    first means the model reads who it is before it reads how everyone behaves.
    """
    filled = house.replace(ALL_NAMES_TOKEN, _join_names(list(AGENT_NAMES.values())))
    return f"{lens.rstrip()}\n\n{filled.lstrip()}"


@lru_cache(maxsize=1)
def agents() -> dict[AgentId, AgentConfig]:
    """Load and cache the agent registry, prompts included."""
    if not HOUSE_PATH.is_file():
        raise FileNotFoundError(f"Missing shared house-style prompt: {HOUSE_PATH}")
    house = HOUSE_PATH.read_text(encoding="utf-8")

    registry: dict[AgentId, AgentConfig] = {}
    for agent_id in AGENT_IDS:
        path = PROMPT_DIR / f"{agent_id}.md"
        if not path.is_file():
            raise FileNotFoundError(f"Missing system prompt for {agent_id}: {path}")
        registry[agent_id] = AgentConfig(
            id=agent_id,
            name=AGENT_NAMES[agent_id],
            system_prompt=compose_prompt(
                agent_id, path.read_text(encoding="utf-8"), house
            ),
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
