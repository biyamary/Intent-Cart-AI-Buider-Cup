import asyncio
import json
from uuid import uuid4

from fastapi import HTTPException
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from app.config import Settings


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
                ):
                    if event.is_final_response() and event.content:
                        final_text = "".join(part.text for part in event.content.parts if part.text)
                if not final_text:
                    raise ValueError("Agent returned no structured final response")
                return schema.model_validate_json(final_text)
        except TimeoutError:
            raise HTTPException(504, "The assistant timed out. Please retry.") from None
        except Exception:
            raise HTTPException(502, "The assistant could not produce a valid response.") from None
        finally:
            await session_service.delete_session(
                app_name=app_name, user_id=uid, session_id=session_id
            )
