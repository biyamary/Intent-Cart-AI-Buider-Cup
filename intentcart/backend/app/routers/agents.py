from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile

from app.agents.conversation_schemas import (
    AgentInfo,
    Attachment,
    ChatRequest,
    Conversation,
    ConversationSummary,
    TurnStatus,
)
from app.agents.conversations import ConversationService
from app.auth import current_user
from app.dependencies import get_store, profile_for
from app.memory.store import Store

router = APIRouter(prefix="/agents", tags=["agent conversations"])


def conversations(request: Request) -> ConversationService:
    return request.app.state.conversations


@router.get("", response_model=list[AgentInfo])
async def list_agents(
    uid: str = Depends(current_user), service: ConversationService = Depends(conversations)
):
    return service.available_agents()


@router.post("/{agent_id}/sessions", response_model=Conversation, status_code=201)
async def create_conversation(
    agent_id: str,
    uid: str = Depends(current_user),
    service: ConversationService = Depends(conversations),
):
    return await service.create(agent_id, uid)


@router.get("/{agent_id}/sessions", response_model=list[ConversationSummary])
async def list_conversations(
    agent_id: str,
    uid: str = Depends(current_user),
    service: ConversationService = Depends(conversations),
):
    return await service.list(agent_id, uid)


@router.get("/{agent_id}/sessions/{session_id}", response_model=Conversation)
async def get_conversation(
    agent_id: str,
    session_id: str,
    uid: str = Depends(current_user),
    service: ConversationService = Depends(conversations),
):
    return await service.get(agent_id, uid, session_id)


@router.post("/{agent_id}/sessions/{session_id}/messages", response_model=Conversation)
async def send_message(
    agent_id: str,
    session_id: str,
    body: ChatRequest,
    uid: str = Depends(current_user),
    store: Store = Depends(get_store),
    service: ConversationService = Depends(conversations),
):
    return await service.send(agent_id, uid, session_id, body, await profile_for(store, uid))


@router.post(
    "/{agent_id}/sessions/{session_id}/turns",
    response_model=TurnStatus,
    status_code=202,
)
async def accept_turn(
    agent_id: str,
    session_id: str,
    body: ChatRequest,
    uid: str = Depends(current_user),
    store: Store = Depends(get_store),
    service: ConversationService = Depends(conversations),
):
    """Accept a turn for background execution; poll its request_id for progress."""
    return await service.accept(agent_id, uid, session_id, body, await profile_for(store, uid))


@router.get(
    "/{agent_id}/sessions/{session_id}/turns/{request_id}", response_model=TurnStatus
)
async def get_turn(
    agent_id: str,
    session_id: str,
    request_id: UUID,
    uid: str = Depends(current_user),
    service: ConversationService = Depends(conversations),
):
    return await service.get_turn(agent_id, uid, session_id, request_id)


@router.post(
    "/{agent_id}/sessions/{session_id}/attachments", response_model=Attachment, status_code=201
)
async def upload_attachment(
    agent_id: str,
    session_id: str,
    image: UploadFile = File(...),
    uid: str = Depends(current_user),
    service: ConversationService = Depends(conversations),
):
    data = await image.read(5 * 1024 * 1024 + 1)
    await image.close()
    name = await service.save_attachment(
        agent_id, uid, session_id, data, image.content_type or ""
    )
    return Attachment(name=name)


@router.get("/{agent_id}/sessions/{session_id}/artifacts/{name}", include_in_schema=False)
async def read_artifact(
    agent_id: str,
    session_id: str,
    name: str,
    uid: str = Depends(current_user),
    service: ConversationService = Depends(conversations),
):
    part = await service.load_artifact(agent_id, uid, session_id, name)
    if part is None or part.inline_data is None:
        raise HTTPException(404, "Image not found.")
    return Response(
        content=part.inline_data.data,
        media_type=part.inline_data.mime_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )
