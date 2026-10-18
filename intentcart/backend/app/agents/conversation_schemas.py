from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.schemas import Contract


class AgentInfo(Contract):
    id: str
    name: str
    enabled: bool
    capabilities: list[str] = Field(default_factory=list)


AttachmentName = Annotated[str, StringConstraints(pattern=r"^ref-[0-9a-f]{12}\.(jpg|png|webp)$")]


class ChatRequest(Contract):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    request_id: UUID
    attachments: list[AttachmentName] = Field(default_factory=list, max_length=3)


class Attachment(Contract):
    name: str


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
    attachments: list[str] = Field(default_factory=list)


class ConversationSummary(Contract):
    id: str
    agent_id: str
    title: str
    updated_at: float


class Conversation(ConversationSummary):
    messages: list[ChatMessage] = Field(default_factory=list)
    look_id: str | None = None
