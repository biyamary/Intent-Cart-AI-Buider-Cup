from typing import Literal
from uuid import UUID

from pydantic import Field, StringConstraints
from typing_extensions import Annotated

from app.schemas import Contract


class AgentInfo(Contract):
    id: str
    name: str
    enabled: bool
    capabilities: list[str] = Field(default_factory=list)


class ChatRequest(Contract):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    request_id: UUID


class Source(Contract):
    title: str
    url: str


class Citation(Contract):
    text: str
    source_indices: list[int]


class ChatMessage(Contract):
    id: str
    role: Literal["user", "assistant"]
    text: str
    created_at: float
    status: Literal["complete", "error"] = "complete"
    sources: list[Source] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    search_entry_point: str | None = None


class ConversationSummary(Contract):
    id: str
    agent_id: str
    title: str
    updated_at: float


class Conversation(ConversationSummary):
    messages: list[ChatMessage] = Field(default_factory=list)
