"""Wire types.

Field aliases keep the JSON contract camelCase, identical to what the existing
Next.js client already sends and expects, while the Python side stays snake_case.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentId = Literal["introspector", "behaviorist", "gardener"]
# Who "spoke" a given line in the visible transcript.
Speaker = Literal["user", "introspector", "behaviorist", "gardener"]


class CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ChatMessage(CamelModel):
    role: Speaker
    content: str


class TurnRequest(CamelModel):
    transcript: list[ChatMessage] = Field(min_length=1)
    # Omit to let the server choose the next speaker — this is the normal path
    # now that turn order lives here rather than in the browser. Pin it only to
    # force a specific agent (tests, or a "hear from X" affordance).
    agent_id: AgentId | None = Field(default=None, alias="agentId")
    # Attributes the generated turn to a stored conversation. Optional: a turn
    # taken before anything is saved still gets recorded, just unattributed.
    conversation_id: str | None = Field(default=None, alias="conversationId")


class TurnResponse(CamelModel):
    agent_id: AgentId = Field(serialization_alias="agentId")
    text: str


class ErrorResponse(BaseModel):
    error: str


class NextSpeakerRequest(CamelModel):
    transcript: list[ChatMessage] = Field(min_length=1)


class NextSpeakerResponse(CamelModel):
    agent_id: AgentId = Field(serialization_alias="agentId")


# ── Conversation history ────────────────────────────────────────────────────


class ConversationSummary(CamelModel):
    """A sidebar row. Carries no transcript — the list view never needs one."""

    id: str
    title: str
    updated_at: int = Field(serialization_alias="updatedAt")
    message_count: int = Field(serialization_alias="messageCount")


class ConversationDetail(CamelModel):
    id: str
    title: str
    updated_at: int = Field(serialization_alias="updatedAt")
    transcript: list[ChatMessage]


class SaveConversationRequest(CamelModel):
    title: str
    transcript: list[ChatMessage]
