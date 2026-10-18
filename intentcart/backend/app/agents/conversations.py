"""Application-owned ADK runners and user-scoped conversational sessions."""

import asyncio
import logging
from uuid import uuid4

from fastapi import HTTPException
from google.adk.agents.run_config import RunConfig
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
from app.agents.registry import AGENTS, AgentRegistration
from app.config import Settings
from app.schemas import Profile

logger = logging.getLogger(__name__)


def create_session_service(settings: Settings) -> BaseSessionService:
    if settings.agent_session_backend == "memory":
        return InMemorySessionService()
    path = settings.agent_session_db_path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{path.as_posix()}")


class ConversationService:
    def __init__(self, settings: Settings, sessions: BaseSessionService):
        self.settings = settings
        self.sessions = sessions
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
                agent=registration.factory(self.settings),
                app_name=registration.app_name,
                session_service=self.sessions,
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
        default_title = "New review" if agent_id == "food" else "New look"
        return ConversationSummary(
            id=session.id,
            agent_id=agent_id,
            title=session.state.get("chat:title", default_title),
            updated_at=session.last_update_time,
        )

    async def get(self, agent_id: str, uid: str, session_id: str) -> Conversation:
        session = await self.get_session(agent_id, uid, session_id)
        root_name = self.runner(agent_id).agent.name
        messages = [
            message for event in session.events if (message := public_message(event, root_name))
        ]
        return Conversation(**self.summary(agent_id, session).model_dump(), messages=messages)

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
        default_title = "New review" if agent_id == "food" else "New look"
        session = await self.sessions.create_session(
            app_name=registration.app_name,
            user_id=uid,
            session_id=uuid4().hex,
            state={"chat:title": default_title},
        )
        return Conversation(**self.summary(agent_id, session).model_dump())

    async def send(
        self, agent_id: str, uid: str, session_id: str, body: ChatRequest, profile: Profile
    ) -> Conversation:
        self.require_enabled(agent_id)
        key = (agent_id, uid, session_id)
        # region agent log
        def _agent_dbg(hypothesis_id, location, message, **data):
            import json, time
            with open(r"c:\code\Intent-Cart-AI-Buider-Cup\debug-d1c5c0.log", "a", encoding="utf-8") as _f:
                _f.write(json.dumps({"sessionId":"d1c5c0","runId":"pre-fix","hypothesisId":hypothesis_id,"location":location,"message":message,"data":data,"timestamp":int(time.time()*1000)})+"\n")
        # endregion
        if key in self._active:
            # region agent log
            _agent_dbg("D", "conversations.py:send", "blocked_active_turn", agent_id=agent_id, active_count=len(self._active))
            # endregion
            raise HTTPException(409, "A reply is already in progress for this conversation.")
        self._active.add(key)
        # region agent log
        _agent_dbg("B", "conversations.py:send", "turn_start", agent_id=agent_id, timeout_s=self.settings.agent_timeout_seconds, text_len=len(body.text), active_count=len(self._active))
        started = __import__("time").perf_counter()
        # endregion
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
            if session.state.get("chat:title") in ("New look", "New review"):
                state_delta["chat:title"] = body.text[:80]
            try:
                async with asyncio.timeout(self.settings.agent_timeout_seconds):
                    has_answer = False
                    async for event in runner.run_async(
                        user_id=uid,
                        session_id=session_id,
                        new_message=types.Content(
                            role="user", parts=[types.Part.from_text(text=body.text)]
                        ),
                        state_delta=state_delta,
                        run_config=RunConfig(max_llm_calls=self.settings.agent_max_llm_calls),
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
                # region agent log
                _agent_dbg("B", "conversations.py:send", "turn_failed", agent_id=agent_id, error_type=type(error).__name__, status=failure.status, reason=failure.reason, elapsed_s=round(__import__("time").perf_counter()-started, 2), detail_prefix=failure.detail[:40])
                # endregion
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
            # region agent log
            _agent_dbg("B", "conversations.py:send", "turn_ok", agent_id=agent_id, elapsed_s=round(__import__("time").perf_counter()-started, 2), has_answer=True)
            # endregion
            return await self.get(agent_id, uid, session_id)
        finally:
            self._active.discard(key)
            # region agent log
            _agent_dbg("D", "conversations.py:send", "turn_unlocked", agent_id=agent_id, active_count=len(self._active))
            # endregion

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
