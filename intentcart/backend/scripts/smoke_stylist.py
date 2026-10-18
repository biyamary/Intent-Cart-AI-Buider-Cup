"""Explicit opt-in live smoke test: two Gemini turns with configured capabilities.

From backend/: uv run python -m scripts.smoke_stylist
Uses only a synthetic shopping brief; no saved user profiles or conversation data.
"""

import asyncio
from uuid import uuid4

from fastapi import HTTPException
from google.adk.sessions import InMemorySessionService

from app.agents.conversation_schemas import ChatRequest
from app.agents.conversations import ConversationService
from app.agents.google_client import configure_adk_environment
from app.config import Settings
from app.schemas import Profile


async def main():
    settings = Settings(stylist_agent_mode="gemini", agent_session_backend="memory")
    configure_adk_environment(settings)
    service = ConversationService(settings, InMemorySessionService())
    search_enabled = settings.stylist_search_enabled
    print(f"Google Search enabled: {search_enabled}", flush=True)
    try:
        session = await service.create("stylist", "synthetic-smoke-user")
        for text in [
            "I want an outfit for my sister's mehendi.",
            "My total budget is INR 6000, shopping in India. I'd like a green kurta set, "
            "comfortable for a daytime outdoor event. "
            + (
                "Please use Google Search to find two current options with source links."
                if search_enabled
                else "Suggest two outfit combinations and budget targets."
            ),
        ]:
            result = await service.send(
                "stylist",
                "synthetic-smoke-user",
                session.id,
                ChatRequest(text=text, request_id=uuid4()),
                Profile(),
            )
            answer = result.messages[-1]
            print(answer.text[:1200], flush=True)
            print(
                f"Search queries: {len(answer.search_queries)}; source links: {len(answer.sources)}",
                flush=True,
            )
        if search_enabled and not result.messages[-1].sources:
            raise RuntimeError("No grounding source links returned by the live search check.")
        print("Live conversational check passed with configured capabilities.", flush=True)
    finally:
        await service.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except HTTPException as error:
        print(f"Live check failed ({error.status_code}): {error.detail}")
        raise SystemExit(1) from None
    except RuntimeError as error:
        print(str(error))
        raise SystemExit(1) from None
