"""Explicit opt-in live smoke test of the full Shop a Look flow.

From backend/:  uv run python -m scripts.smoke_shop_look [--images]

Runs real Gemini turns, Google Search grounding and live store-page fetches with a
synthetic brief and in-memory storage. Prints each item's verified candidates.
--images also generates one concept image. This incurs normal API costs.
"""

import argparse
import asyncio
import sys
from uuid import uuid4

from fastapi import HTTPException
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService

from app.agents.conversation_schemas import ChatRequest
from app.agents.conversations import ConversationService
from app.agents.google_client import configure_adk_environment
from app.clothes.discovery import Discovery
from app.clothes.service import LookService
from app.clothes.studio import Studio
from app.clothes.tools import ShopServices
from app.config import Settings
from app.memory.store import MemoryStore
from app.schemas import Profile

USER = "synthetic-smoke-user"


async def main(images: bool):
    settings = Settings(
        stylist_agent_mode="gemini",
        stylist_search_enabled=True,
        stylist_images_enabled=images,
        agent_session_backend="memory",
        artifact_backend="memory",
    )
    configure_adk_environment(settings)
    looks = LookService(MemoryStore())
    discovery = Discovery(settings, looks)
    services = ShopServices(settings, looks, discovery, Studio(settings))
    service = ConversationService(
        settings, InMemorySessionService(), InMemoryArtifactService(), services
    )
    turns = [
        (
            "Help me put together a look for my sister's mehendi. Mint green lehenga with "
            "mirror work, oxidised silver jewellery. Total budget INR 9000, shopping in India, "
            "I prefer small businesses. I already own suitable footwear."
        ),
        "That checklist looks good, please start shopping.",
    ]
    if images:
        turns.append("While that runs, can you show me an AI concept of the look?")
    try:
        session = await service.create("stylist", USER)
        for text in turns:
            print(f"\n>>> {text}", flush=True)
            result = await service.send(
                "stylist", USER, session.id, ChatRequest(text=text, request_id=uuid4()), Profile()
            )
            print(result.messages[-1].text[:1500], flush=True)
        look_id = result.look_id
        if not look_id:
            raise RuntimeError("The stylist did not create a look.")
        print("\nWaiting for background discovery…", flush=True)
        await discovery.wait_idle()
        look = await looks.get(USER, look_id)
        print(f"\nLook: {look.brief.occasion} · status {look.status} · concepts {len(look.concepts)}")
        for item in look.items:
            print(f"\n[{item.category}] {item.status} · {item.discovery} · {item.discovery_note}")
            print(f"  target: {item.target}")
            for p in item.candidates:
                print(
                    f"  - ₹{p.price_minor // 100:,} {p.title[:60]} | {p.retailer} | "
                    f"{p.seller_label} | fit {p.style_score} | {p.verification}\n    {p.url}"
                )
        if not any(item.candidates for item in look.items):
            raise RuntimeError("No verified candidates were found for any item.")
        print("\nLive Shop a Look check passed.")
    finally:
        await discovery.close()
        await service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", action="store_true")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        asyncio.run(main(parser.parse_args().images))
    except HTTPException as error:
        print(f"Live check failed ({error.status_code}): {error.detail}")
        raise SystemExit(1) from None
    except RuntimeError as error:
        print(str(error))
        raise SystemExit(1) from None
