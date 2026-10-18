"""One-shot specialist agent runs that keep grounding sources.

Google Search / Maps grounded agents cannot use `output_schema`, so they return
JSON text. Their grounding metadata is kept separately: these are the URLs the
provider actually retrieved, as opposed to URLs the model wrote.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.privacy import adk_app, is_node_failure


@dataclass
class Source:
    uri: str
    title: str = ""
    kind: str = "web"  # web | maps


@dataclass
class AgentResult:
    text: str
    sources: list[Source] = field(default_factory=list)


def grounding_sources(metadata: types.GroundingMetadata | None) -> list[Source]:
    sources = []
    for chunk in (metadata.grounding_chunks if metadata else None) or []:
        if chunk.web and chunk.web.uri:
            sources.append(Source(chunk.web.uri, chunk.web.title or ""))
        elif getattr(chunk, "maps", None) and chunk.maps.uri:
            sources.append(Source(chunk.maps.uri, chunk.maps.title or "", "maps"))
    return sources


def collect_grounding(into: list[Source]):
    """after_model_callback that records grounding sources without changing the response."""

    def callback(callback_context, llm_response):
        into.extend(grounding_sources(llm_response.grounding_metadata))

    return callback


async def run_once(
    agent,
    parts: list[types.Part],
    *,
    user_id: str = "intentcart-system",
    timeout: float = 60,
    max_llm_calls: int = 6,
) -> AgentResult:
    """Run `agent` in a throwaway session and return its final public text."""
    sessions = InMemorySessionService()
    app_name, session_id = "intentcart_specialist", uuid4().hex
    runner = Runner(app=adk_app(app_name, agent), session_service=sessions)
    await sessions.create_session(app_name=app_name, user_id=user_id, session_id=session_id)
    text, sources = "", []
    try:
        async with asyncio.timeout(timeout):
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=types.Content(role="user", parts=parts),
                run_config=RunConfig(max_llm_calls=max_llm_calls),
            ):
                if is_node_failure(event):
                    continue
                sources.extend(grounding_sources(event.grounding_metadata))
                if event.author == agent.name and event.is_final_response() and event.content:
                    text = "".join(
                        p.text for p in event.content.parts or [] if p.text and not p.thought
                    )
    finally:
        await runner.close()
    return AgentResult(text=text, sources=sources)


def parse_json(text: Any) -> Any:
    """Parse model JSON, tolerating code fences and surrounding prose."""
    if isinstance(text, (dict, list)):
        return text
    if hasattr(text, "model_dump"):
        return text.model_dump()
    raw = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = raw.find(opener), raw.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


URL_RE = re.compile(r"https://[^\s\"'<>()\[\]{}]+")


def urls_in(text: Any) -> list[str]:
    """Every https URL in model output, in order; used when its JSON is malformed."""
    return list(dict.fromkeys(m.rstrip(".,;:") for m in URL_RE.findall(str(text or ""))))
