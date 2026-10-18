"""Application-owned ADK runners and user-scoped conversational sessions."""

import asyncio
import logging
import re
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from google.adk.agents.run_config import RunConfig
from google.adk.artifacts import (
    BaseArtifactService,
    FileArtifactService,
    GcsArtifactService,
    InMemoryArtifactService,
)
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, DatabaseSessionService, InMemorySessionService
from google.genai import types

from app.agents.conversation_schemas import (
    AgentInfo,
    ChatRequest,
    Conversation,
    ConversationSummary,
)
from app.agents.errors import describe_agent_error
from app.agents.grounding import public_message
from app.agents.privacy import adk_app, install_log_redaction
from app.agents.registry import AGENTS, AgentRegistration
from app.config import Settings
from app.schemas import Profile

logger = logging.getLogger(__name__)
install_log_redaction()


def create_session_service(settings: Settings) -> BaseSessionService:
    if settings.agent_session_backend == "memory":
        return InMemorySessionService()
    path = settings.agent_session_db_path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{path.as_posix()}")


def create_artifact_service(settings: Settings) -> BaseArtifactService:
    if settings.artifact_backend == "memory":
        return InMemoryArtifactService()
    if settings.artifact_backend == "gcs":
        return GcsArtifactService(bucket_name=settings.artifact_bucket)
    return FileArtifactService(root_dir=settings.artifact_dir)


IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}
IMAGE_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def valid_image(data: bytes, mime: str) -> bool:
    if not any(data.startswith(sig) for sig in IMAGE_SIGNATURES.get(mime, ())):
        return False
    return mime != "image/webp" or data[8:12] == b"WEBP"


class ConversationService:
    def __init__(
        self,
        settings: Settings,
        sessions: BaseSessionService,
        artifacts: BaseArtifactService | None = None,
        services: Any = None,
    ):
        self.settings = settings
        self.sessions = sessions
        self.artifacts = artifacts or InMemoryArtifactService()
        # App-level adapters handed to agent factories (e.g. look storage for the stylist).
        self.services = services
        self.runners: dict[str, Runner] = {}
        # Whole-turn serialization. The current deployment contract is one worker.
        # Distributed deployments need a shared per-session lease, not only DB event locks.
        self._active: set[tuple[str, str, str]] = set()

    def registration(self, agent_id: str) -> AgentRegistration:
        registration = AGENTS.get(agent_id)
        if registration is None:
            raise HTTPException(404, "Agent not found.")
        return registration

    def available_agents(self) -> list[AgentInfo]:
        return [
            AgentInfo(
                id=agent.key,
                name=agent.display_name,
                enabled=agent.enabled(self.settings),
                capabilities=agent.capabilities(self.settings)
                if agent.enabled(self.settings)
                else [],
            )
            for agent in AGENTS.values()
        ]

    def runner(self, agent_id: str) -> Runner:
        registration = self.registration(agent_id)
        if agent_id not in self.runners:
            self.runners[agent_id] = Runner(
                app=adk_app(
                    registration.app_name, registration.factory(self.settings, self.services)
                ),
                session_service=self.sessions,
                artifact_service=self.artifacts,
            )
        return self.runners[agent_id]

    def require_enabled(self, agent_id: str):
        if not self.registration(agent_id).enabled(self.settings):
            raise HTTPException(
                503, "This assistant is not connected yet. Live chat must be enabled on the server."
            )

    async def get_session(self, agent_id: str, uid: str, session_id: str):
        registration = self.registration(agent_id)
        session = await self.sessions.get_session(
            app_name=registration.app_name, user_id=uid, session_id=session_id
        )
        if session is None:
            raise HTTPException(404, "Conversation not found.")
        return session

    def summary(self, agent_id: str, session) -> ConversationSummary:
        return ConversationSummary(
            id=session.id,
            agent_id=agent_id,
            title=session.state.get("chat:title", self.registration(agent_id).default_title),
            updated_at=session.last_update_time,
        )

    async def get(self, agent_id: str, uid: str, session_id: str) -> Conversation:
        session = await self.get_session(agent_id, uid, session_id)
        root_name = self.runner(agent_id).agent.name
        messages = [
            message for event in session.events if (message := public_message(event, root_name))
        ]
        return Conversation(
            **self.summary(agent_id, session).model_dump(),
            messages=messages,
            look_id=session.state.get("look:id"),
        )

    async def list(self, agent_id: str, uid: str) -> list[ConversationSummary]:
        registration = self.registration(agent_id)
        result = await self.sessions.list_sessions(app_name=registration.app_name, user_id=uid)
        return sorted(
            [self.summary(agent_id, session) for session in result.sessions],
            key=lambda session: session.updated_at,
            reverse=True,
        )

    async def create(self, agent_id: str, uid: str) -> Conversation:
        self.require_enabled(agent_id)
        registration = self.registration(agent_id)
        session = await self.sessions.create_session(
            app_name=registration.app_name,
            user_id=uid,
            session_id=uuid4().hex,
            state={"chat:title": registration.default_title},
        )
        return Conversation(**self.summary(agent_id, session).model_dump())

    async def send(
        self, agent_id: str, uid: str, session_id: str, body: ChatRequest, profile: Profile
    ) -> Conversation:
        self.require_enabled(agent_id)
        key = (agent_id, uid, session_id)
        if key in self._active:
            raise HTTPException(409, "A reply is already in progress for this conversation.")
        self._active.add(key)
        try:
            session = await self.get_session(agent_id, uid, session_id)
            request_id = str(body.request_id)
            if any(
                event.actions.state_delta.get("chat:request_id") == request_id
                for event in session.events
            ):
                # A retried HTTP request cannot spend another model call or duplicate the turn.
                return await self.get(agent_id, uid, session_id)
            if (
                sum(event.author == "user" for event in session.events)
                >= self.settings.agent_max_conversation_turns
            ):
                item_name = "review" if agent_id == "food" else "look"
                raise HTTPException(
                    409, f"This conversation has reached its limit. Start a new {item_name} to continue."
                )
            registration = self.registration(agent_id)
            runner = self.runner(agent_id)
            state_delta = {
                "chat:request_id": request_id,
                "temp:profile": registration.profile_context(profile),
            }
            if body.attachments:
                if not registration.accepts_images:
                    raise HTTPException(422, "This assistant does not accept images.")
                for name in body.attachments:
                    if await self.load_artifact(agent_id, uid, session_id, name) is None:
                        raise HTTPException(422, "An attached image is no longer available.")
                state_delta["chat:attachments"] = list(body.attachments)
                state_delta["temp:attachments"] = list(body.attachments)
            if session.state.get("chat:title") == registration.default_title:
                state_delta["chat:title"] = body.text[:80]
            try:
                async with asyncio.timeout(registration.timeout_seconds(self.settings)):
                    has_answer = False
                    async for event in runner.run_async(
                        user_id=uid,
                        session_id=session_id,
                        new_message=types.Content(
                            role="user", parts=[types.Part.from_text(text=body.text)]
                        ),
                        state_delta=state_delta,
                        run_config=RunConfig(
                            max_llm_calls=registration.max_llm_calls(self.settings)
                        ),
                    ):
                        message = public_message(event, runner.agent.name)
                        if message and message.role == "assistant" and message.status == "complete":
                            has_answer = True
                    if not has_answer:
                        raise ValueError("No public assistant reply")
            except asyncio.CancelledError:
                await self.record_failure(
                    agent_id,
                    uid,
                    session_id,
                    request_id,
                    "The reply was interrupted. Send a follow-up to continue.",
                )
                raise
            except Exception as error:
                failure = describe_agent_error(error)
                # No exception text, prompts, API keys, URLs or user content in logs.
                logger.warning(
                    "Agent turn failed: agent=%s error_type=%s status=%s reason=%s retry_after=%s",
                    agent_id,
                    type(error).__name__,
                    failure.status,
                    failure.reason,
                    failure.retry_after,
                )
                await self.record_failure(agent_id, uid, session_id, request_id, failure.detail)
                headers = (
                    {"Retry-After": str(failure.retry_after)}
                    if failure.retry_after is not None
                    else None
                )
                raise HTTPException(failure.status, failure.detail, headers=headers) from None
            return await self.get(agent_id, uid, session_id)
        finally:
            self._active.discard(key)

    async def save_attachment(
        self, agent_id: str, uid: str, session_id: str, data: bytes, mime: str
    ) -> str:
        registration = self.registration(agent_id)
        if not registration.accepts_images:
            raise HTTPException(422, "This assistant does not accept images.")
        await self.get_session(agent_id, uid, session_id)
        if mime not in IMAGE_EXTENSIONS:
            raise HTTPException(415, "Use a JPEG, PNG or WebP image.")
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Choose a non-empty image smaller than 5 MB.")
        if not valid_image(data, mime):
            raise HTTPException(415, "The file is not a valid JPEG, PNG or WebP image.")
        name = f"ref-{uuid4().hex[:12]}.{IMAGE_EXTENSIONS[mime]}"
        try:
            await self.artifacts.save_artifact(
                app_name=registration.app_name,
                user_id=uid,
                session_id=session_id,
                filename=name,
                artifact=types.Part.from_bytes(data=data, mime_type=mime),
            )
        except OSError:
            # e.g. Windows path-length limits with a deep ARTIFACT_DIR (see docs/agents.md).
            logger.warning("Attachment storage failed: agent=%s", agent_id)
            raise HTTPException(503, "The image could not be stored. Try again later.") from None
        return name

    async def load_artifact(self, agent_id: str, uid: str, session_id: str, name: str):
        """Load a session-scoped artifact; the session must belong to `uid`."""
        registration = self.registration(agent_id)
        await self.get_session(agent_id, uid, session_id)
        if not re.fullmatch(r"(ref|concept)-[0-9a-f]{10,12}\.(jpg|png|webp)", name):
            return None
        return await self.artifacts.load_artifact(
            app_name=registration.app_name, user_id=uid, session_id=session_id, filename=name
        )

    async def record_failure(
        self, agent_id: str, uid: str, session_id: str, request_id: str, detail: str
    ):
        session = await self.get_session(agent_id, uid, session_id)
        await self.sessions.append_event(
            session=session,
            event=Event(
                author="system",
                actions=EventActions(
                    state_delta={"chat:error": detail, "chat:request_id": request_id}
                ),
            ),
        )

    async def close(self):
        for runner in self.runners.values():
            await runner.close()
        if isinstance(self.sessions, DatabaseSessionService):
            await self.sessions.close()
