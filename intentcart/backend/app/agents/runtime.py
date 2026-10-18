import asyncio
import json
import logging
from uuid import uuid4

from fastapi import HTTPException
from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from app.agents.errors import StructuredResponseError, describe_step_error, ensure_complete_response
from app.config import Settings

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Short-lived ADK sessions; durable, user-confirmed workflow state lives in Store.

    Each invocation receives explicit context. Do not serialize ADK internal events
    into user-visible progress. Production conversational memory is a future adapter.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    async def run(
        self,
        agent,
        uid: str,
        payload: dict,
        schema: type[BaseModel],
        image: bytes | None = None,
        mime: str | None = None,
    ):
        if self.settings.agent_mode != "gemini":
            raise HTTPException(501, "Gemini is not enabled. This is a local demo.")
        if "TODO_PROMPT" in str(agent.instruction):
            raise HTTPException(
                501, "Replace this agent's TODO_PROMPT file before enabling live generation."
            )
        session_service = InMemorySessionService()
        app_name, session_id = "intentcart", uuid4().hex
        runner = Runner(agent=agent, app_name=app_name, session_service=session_service)
        await session_service.create_session(app_name=app_name, user_id=uid, session_id=session_id)
        parts = [types.Part.from_text(text=json.dumps(payload))]
        if image is not None:
            parts.append(types.Part.from_bytes(data=image, mime_type=mime))
        try:
            async with asyncio.timeout(self.settings.agent_timeout_seconds):
                final_text = None
                async for event in runner.run_async(
                    user_id=uid,
                    session_id=session_id,
                    new_message=types.Content(role="user", parts=parts),
                    run_config=RunConfig(max_llm_calls=self.settings.agent_max_llm_calls),
                ):
                    if event.author == agent.name:
                        ensure_complete_response(event)
                    if event.author == agent.name and event.is_final_response() and event.content:
                        final_text = "".join(
                            part.text
                            for part in event.content.parts
                            if part.text and not part.thought
                        )
                if not final_text:
                    raise StructuredResponseError("empty_response")
                # Research uses tools without output_schema for Gemini compatibility.
                if final_text.strip().startswith("```"):
                    final_text = final_text.strip().partition("\n")[2].rsplit("```", 1)[0]
                return schema.model_validate_json(final_text)
        except Exception as error:  # noqa: BLE001 -- redact all SDK failures at the API boundary
            failure = describe_step_error(error)
            # Never log exception messages/tracebacks: provider payloads may contain
            # credentials, uploaded image data, prompts or generated label text.
            logger.warning(
                "Agent step failed: agent=%s error_type=%s status=%s reason=%s retry_after=%s",
                agent.name,
                type(error).__name__,
                failure.status,
                failure.reason,
                failure.retry_after,
            )
            headers = (
                {"Retry-After": str(failure.retry_after)}
                if failure.retry_after is not None
                else None
            )
            raise HTTPException(failure.status, failure.detail, headers=headers) from None
        finally:
            await session_service.delete_session(
                app_name=app_name, user_id=uid, session_id=session_id
            )
