from fastapi import APIRouter, Depends, Request

from app.agents.conversation_schemas import (
    AgentInfo,
    ChatRequest,
    Conversation,
    ConversationSummary,
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
