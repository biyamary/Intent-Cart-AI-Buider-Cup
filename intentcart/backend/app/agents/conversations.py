"""Application-owned ADK runners and user-scoped conversational sessions."""

import asyncio
import logging
import re
import time
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

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
    DeletedConversations,
    RetryAdvice,
    TurnError,
    TurnProgress,
    TurnStatus,
)
from app.agents.errors import AgentFailure, StructuredResponseError, describe_agent_error
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

PROGRESS_LABELS = {
    "queued": "Waiting to start",
    "understanding": "Understanding your request",
    "planning": "Planning the next steps",
    "searching": "Searching stores and sources",
    "researching": "Checking trusted food sources",
    "preparing": "Preparing your answer",
    "complete": "Reply ready",
    "failed": "Reply needs attention",
}

PLANNING_TOOLS = {
    "save_brief",
    "propose_checklist",
    "update_checklist",
    "start_shopping",
    "select_product",
    "change_item",
    "finish_look",
}
SEARCH_TOOLS = {
    "find_products",
    "find_alternatives",
    "find_inspiration",
    "find_local_boutiques",
    "add_product_link",
    "analyze_reference",
    "visualize_look",
}
RESEARCH_TOOLS = {
    "lookup_ingredient_database",
    "check_regulations",
    "fetch_food_evidence",
    "food_google_search",
}


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
        # Accepted turns run only in this process. Their lifecycle is persisted in ADK
        # events, but multi-worker execution requires a shared queue and distributed lease.
        self._tasks: dict[tuple[str, str, str, str], asyncio.Task] = {}
        # Mid-run progress stages stay in memory. Appending them to the session while
        # the runner holds it makes the runner's next append stale, which SQL-backed
        # session services reject (StaleSessionError) after any tool call.
        self._live: dict[tuple[str, str, str, str], TurnStatus] = {}

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
        look_id = await self._recover_look_link(agent_id, uid, session)
        root_name = self.runner(agent_id).agent.name
        messages = [
            message for event in session.events if (message := public_message(event, root_name))
        ]
        return Conversation(
            **self.summary(agent_id, session).model_dump(),
            messages=messages,
            look_id=look_id,
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

    async def _recover_look_link(self, agent_id: str, uid: str, session) -> str | None:
        """Find a stylist look whose tool write outlived its provider turn.

        Read-only: a turn may be running, and appending to its session here would make
        the runner's copy stale. The next turn persists the link via its state delta.
        """
        linked = session.state.get("look:id")
        if linked or agent_id != "stylist" or self.services is None:
            return linked
        look = await self.services.looks.find_for_session(uid, session.id)
        return look.id if look else None

    def _turn_from_session(
        self, agent_id: str, session_id: str, session, request_id: str
    ) -> TurnStatus | None:
        """Read the newest persisted lifecycle event for a request."""
        for event in reversed(session.events):
            raw = event.actions.state_delta.get("chat:turn")
            if isinstance(raw, dict) and raw.get("request_id") == request_id:
                try:
                    return TurnStatus.model_validate(raw)
                except (TypeError, ValueError):
                    # Never expose or trust malformed session state.
                    logger.warning("Invalid turn state: agent=%s", agent_id)
                    return None

        # Compatibility with sessions written before lifecycle events existed.
        for event in reversed(session.events):
            if event.actions.state_delta.get("chat:request_id") != request_id:
                continue
            now = event.timestamp
            detail = event.actions.state_delta.get("chat:error")
            if isinstance(detail, str):
                return TurnStatus(
                    request_id=UUID(request_id),
                    agent_id=agent_id,
                    session_id=session_id,
                    status="failed",
                    progress=TurnProgress(stage="failed", label=PROGRESS_LABELS["failed"]),
                    created_at=now,
                    updated_at=now,
                    error=TurnError(code="legacy_failure", message=detail),
                    retry=RetryAdvice(allowed=True),
                )
            return TurnStatus(
                request_id=UUID(request_id),
                agent_id=agent_id,
                session_id=session_id,
                status="succeeded",
                progress=TurnProgress(stage="complete", label=PROGRESS_LABELS["complete"]),
                created_at=now,
                updated_at=now,
            )
        return None

    def _turn_status(
        self,
        agent_id: str,
        session_id: str,
        request_id: str,
        status: str,
        stage: str,
        *,
        created_at: float,
        failure: AgentFailure | None = None,
    ) -> TurnStatus:
        retry = None
        error = None
        if failure is not None:
            error = TurnError(
                code=failure.reason,
                message=failure.detail,
                diagnostic_id=failure.diagnostic_id,
            )
            retry = RetryAdvice(
                allowed=failure.retryable,
                after_seconds=failure.retry_after,
            )
        return TurnStatus(
            request_id=UUID(request_id),
            agent_id=agent_id,
            session_id=session_id,
            status=status,
            progress=TurnProgress(stage=stage, label=PROGRESS_LABELS[stage]),
            created_at=created_at,
            updated_at=time.time(),
            error=error,
            retry=retry,
        )

    async def _record_turn(self, uid: str, turn: TurnStatus, *, public_error: bool = False):
        session = await self.get_session(turn.agent_id, uid, turn.session_id)
        state_delta: dict[str, Any] = {"chat:turn": turn.model_dump(mode="json")}
        if public_error and turn.error is not None:
            # This one event is both the canonical transcript error and the
            # structured terminal status. Callers must not create another bubble.
            state_delta.update(
                {
                    "chat:error": turn.error.message,
                    "chat:request_id": str(turn.request_id),
                    "chat:failure": {
                        "error": turn.error.model_dump(mode="json"),
                        "retry": turn.retry.model_dump(mode="json") if turn.retry else None,
                    },
                }
            )
        await self.sessions.append_event(
            session=session,
            event=Event(author="system", actions=EventActions(state_delta=state_delta)),
        )
        return turn

    async def _record_progress(
        self,
        agent_id: str,
        uid: str,
        session_id: str,
        request_id: str,
        status: str,
        stage: str,
        created_at: float,
    ) -> TurnStatus:
        turn = self._turn_status(
            agent_id,
            session_id,
            request_id,
            status,
            stage,
            created_at=created_at,
        )
        return await self._record_turn(uid, turn)

    async def get_turn(
        self, agent_id: str, uid: str, session_id: str, request_id: UUID
    ) -> TurnStatus:
        session = await self.get_session(agent_id, uid, session_id)
        request_key = str(request_id)
        turn = self._turn_from_session(agent_id, session_id, session, request_key)
        if turn is None:
            raise HTTPException(404, "Turn not found.")
        session_key = (agent_id, uid, session_id)
        if turn.status == "running" and session_key in self._active:
            return self._live.get((*session_key, request_key), turn)
        if turn.status in {"queued", "running"} and session_key not in self._active:
            # A process restart cannot resume an in-memory task. Persist one clear
            # recovery message instead of leaving the UI polling forever. Taking
            # the local lease before awaiting also prevents concurrent polls from
            # appending the canonical failure twice.
            self._active.add(session_key)
            try:
                current_session = await self.get_session(agent_id, uid, session_id)
                current = self._turn_from_session(
                    agent_id, session_id, current_session, request_key
                )
                if current is not None and current.status in {"failed", "succeeded"}:
                    return current
                registration = self.registration(agent_id)
                failure = AgentFailure(
                    503,
                    f"{registration.failure_subject}'s reply was interrupted. "
                    "Your conversation is saved; send a follow-up to continue.",
                    "interrupted",
                )
                return await self.record_failure(
                    agent_id, uid, session_id, request_key, failure, created_at=turn.created_at
                )
            finally:
                self._active.discard(session_key)
        return turn

    async def _prepare_turn(
        self,
        agent_id: str,
        uid: str,
        session,
        body: ChatRequest,
        profile: Profile,
    ) -> dict[str, Any]:
        if (
            sum(event.author == "user" for event in session.events)
            >= self.settings.agent_max_conversation_turns
        ):
            item_name = "review" if agent_id == "food" else "look"
            raise HTTPException(
                409,
                f"This conversation has reached its limit. Start a new {item_name} to continue.",
            )
        registration = self.registration(agent_id)
        state_delta: dict[str, Any] = {
            "chat:request_id": str(body.request_id),
            "temp:profile": registration.profile_context(profile),
        }
        if look_id := await self._recover_look_link(agent_id, uid, session):
            state_delta["look:id"] = look_id
        if body.attachments:
            if not registration.accepts_images:
                raise HTTPException(422, "This assistant does not accept images.")
            for name in body.attachments:
                if await self.load_artifact(agent_id, uid, session.id, name) is None:
                    raise HTTPException(422, "An attached image is no longer available.")
            state_delta["chat:attachments"] = list(body.attachments)
            state_delta["temp:attachments"] = list(body.attachments)
        if session.state.get("chat:title") == registration.default_title:
            state_delta["chat:title"] = body.text[:80]
        return state_delta

    def _event_progress(self, agent_id: str, event: Event) -> str | None:
        try:
            names = {call.name for call in event.get_function_calls() if call.name}
        except (AttributeError, TypeError):
            names = set()
        if names & RESEARCH_TOOLS or (agent_id == "food" and names):
            return "researching"
        if names & SEARCH_TOOLS:
            return "searching"
        if names & PLANNING_TOOLS:
            return "planning"
        if event.author != "user":
            return "preparing"
        return None

    async def _execute_turn(
        self,
        agent_id: str,
        uid: str,
        session_id: str,
        body: ChatRequest,
        state_delta: dict[str, Any],
        created_at: float,
    ) -> AgentFailure | None:
        request_id = str(body.request_id)
        registration = self.registration(agent_id)
        runner = self.runner(agent_id)
        stage = "understanding"
        invocation_id = None
        live_key = (agent_id, uid, session_id, request_id)
        await self._record_progress(
            agent_id, uid, session_id, request_id, "running", stage, created_at
        )
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
                    run_config=RunConfig(max_llm_calls=registration.max_llm_calls(self.settings)),
                ):
                    invocation_id = event.invocation_id or invocation_id
                    next_stage = self._event_progress(agent_id, event)
                    if next_stage is not None and next_stage != stage:
                        stage = next_stage
                        self._live[live_key] = self._turn_status(
                            agent_id,
                            session_id,
                            request_id,
                            "running",
                            stage,
                            created_at=created_at,
                        )
                    message = public_message(event, runner.agent.name)
                    if message and message.role == "assistant" and message.status == "complete":
                        has_answer = True
                if not has_answer:
                    raise StructuredResponseError("empty_response")
        except asyncio.CancelledError:
            failure = AgentFailure(
                503,
                f"{registration.failure_subject}'s reply was interrupted. "
                "Your conversation is saved; send a follow-up to continue.",
                "interrupted",
            )
            await self.record_failure(
                agent_id, uid, session_id, request_id, failure, created_at=created_at
            )
            raise
        except Exception as error:  # noqa: BLE001 - redact all SDK failures at API boundary
            failure = replace(
                describe_agent_error(error, registration.failure_subject),
                diagnostic_id=uuid4().hex[:12],
            )
            # No exception text, prompts, API keys, URLs or user content in logs.
            logger.warning(
                "Agent turn failed: agent=%s request_id=%s invocation_id=%s diagnostic_id=%s "
                "error_type=%s status=%s reason=%s retry_after=%s",
                agent_id,
                request_id,
                invocation_id,
                failure.diagnostic_id,
                type(error).__name__,
                failure.status,
                failure.reason,
                failure.retry_after,
            )
            await self.record_failure(
                agent_id, uid, session_id, request_id, failure, created_at=created_at
            )
            return failure
        await self._record_progress(
            agent_id, uid, session_id, request_id, "succeeded", "complete", created_at
        )
        return None

    async def accept(
        self, agent_id: str, uid: str, session_id: str, body: ChatRequest, profile: Profile
    ) -> TurnStatus:
        """Persist and start a turn, returning immediately for polling clients."""
        self.require_enabled(agent_id)
        session = await self.get_session(agent_id, uid, session_id)
        request_id = str(body.request_id)
        existing = self._turn_from_session(agent_id, session_id, session, request_id)
        if existing is not None:
            return await self.get_turn(agent_id, uid, session_id, body.request_id)
        session_key = (agent_id, uid, session_id)
        if session_key in self._active:
            raise HTTPException(409, "A reply is already in progress for this conversation.")
        state_delta = await self._prepare_turn(agent_id, uid, session, body, profile)
        self._active.add(session_key)
        created_at = time.time()
        try:
            queued = await self._record_progress(
                agent_id,
                uid,
                session_id,
                request_id,
                "queued",
                "queued",
                created_at,
            )
            task_key = (*session_key, request_id)
            task = asyncio.create_task(
                self._run_accepted(
                    agent_id,
                    uid,
                    session_id,
                    body,
                    state_delta,
                    created_at,
                    session_key,
                ),
                name=f"agent-turn-{agent_id}-{request_id}",
            )
            self._tasks[task_key] = task
            task.add_done_callback(lambda done: self._finish_task(task_key, done))
            return queued
        except Exception:
            self._active.discard(session_key)
            raise

    def _finish_task(self, task_key: tuple[str, str, str, str], task: asyncio.Task):
        self._tasks.pop(task_key, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Accepted turn task stopped unexpectedly: agent=%s error_type=%s",
                task_key[0],
                type(error).__name__,
            )

    async def _run_accepted(
        self,
        agent_id: str,
        uid: str,
        session_id: str,
        body: ChatRequest,
        state_delta: dict[str, Any],
        created_at: float,
        session_key: tuple[str, str, str],
    ):
        try:
            await self._execute_turn(agent_id, uid, session_id, body, state_delta, created_at)
        finally:
            self._live.pop((*session_key, str(body.request_id)), None)
            self._active.discard(session_key)

    async def send(
        self, agent_id: str, uid: str, session_id: str, body: ChatRequest, profile: Profile
    ) -> Conversation:
        self.require_enabled(agent_id)
        session = await self.get_session(agent_id, uid, session_id)
        request_id = str(body.request_id)
        existing = self._turn_from_session(agent_id, session_id, session, request_id)
        if existing is not None:
            return await self.get(agent_id, uid, session_id)
        session_key = (agent_id, uid, session_id)
        if session_key in self._active:
            raise HTTPException(409, "A reply is already in progress for this conversation.")
        state_delta = await self._prepare_turn(agent_id, uid, session, body, profile)
        self._active.add(session_key)
        created_at = time.time()
        try:
            await self._record_progress(
                agent_id,
                uid,
                session_id,
                request_id,
                "queued",
                "queued",
                created_at,
            )
            failure = await self._execute_turn(
                agent_id, uid, session_id, body, state_delta, created_at
            )
            if failure is not None:
                headers = {}
                if failure.retry_after is not None:
                    headers["Retry-After"] = str(failure.retry_after)
                if failure.diagnostic_id:
                    headers["X-Diagnostic-ID"] = failure.diagnostic_id
                raise HTTPException(
                    failure.status, failure.detail, headers=headers or None
                ) from None
            return await self.get(agent_id, uid, session_id)
        finally:
            self._live.pop((*session_key, request_id), None)
            self._active.discard(session_key)

    async def delete_all(self, uid: str) -> DeletedConversations:
        """Permanently delete every conversation of `uid` with its images and looks."""
        # Stop this user's background turns first so none writes to a deleted session.
        tasks = [task for key, task in self._tasks.items() if key[1] == uid]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if any(key[1] == uid for key in self._active):
            raise HTTPException(
                409, "A reply is still in progress. Try again when it finishes."
            )
        deleted: set[str] = set()
        for registration in AGENTS.values():
            app_name = registration.app_name
            listed = await self.sessions.list_sessions(app_name=app_name, user_id=uid)
            for session in listed.sessions:
                names = await self.artifacts.list_artifact_keys(
                    app_name=app_name, user_id=uid, session_id=session.id
                )
                for name in names:
                    if not name.startswith("user:"):
                        await self.artifacts.delete_artifact(
                            app_name=app_name, user_id=uid, session_id=session.id, filename=name
                        )
                await self.sessions.delete_session(
                    app_name=app_name, user_id=uid, session_id=session.id
                )
                deleted.add(session.id)
        looks = 0
        if self.services is not None:
            looks = await self.services.looks.delete_for_sessions(uid, deleted)
        logger.info("Deleted conversations: count=%s looks=%s", len(deleted), looks)
        return DeletedConversations(conversations=len(deleted), looks=looks)

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
        self,
        agent_id: str,
        uid: str,
        session_id: str,
        request_id: str,
        failure: AgentFailure,
        *,
        created_at: float | None = None,
    ) -> TurnStatus:
        session = await self.get_session(agent_id, uid, session_id)
        existing = self._turn_from_session(agent_id, session_id, session, request_id)
        if existing is not None and existing.status in {"failed", "succeeded"}:
            return existing
        turn = self._turn_status(
            agent_id,
            session_id,
            request_id,
            "failed",
            "failed",
            created_at=created_at or (existing.created_at if existing else time.time()),
            failure=failure,
        )
        return await self._record_turn(uid, turn, public_error=True)

    async def close(self):
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for runner in self.runners.values():
            await runner.close()
        if isinstance(self.sessions, DatabaseSessionService):
            await self.sessions.close()
