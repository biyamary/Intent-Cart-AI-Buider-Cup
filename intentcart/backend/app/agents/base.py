"""Shared construction policy; ADK's LlmAgent remains the actual base agent.

Use composition: each vertical owns its prompt and tools, while the application
owns sessions, identity, limits and transport. Never store user state on an agent.
"""

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.genai import types
from pydantic import BaseModel

PROMPT_DIR = Path(__file__).with_name("prompts")


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    prompt_file: str


def retrying(attempts: int) -> types.HttpOptions:
    """Back off and retry transient quota/capacity errors (429/503) for this agent only."""
    return types.HttpOptions(
        retry_options=types.HttpRetryOptions(
            attempts=attempts, initial_delay=2, max_delay=15, http_status_codes=[429, 503]
        )
    )


def create_agent(
    definition: AgentDefinition,
    *,
    model: str,
    tools: list[BaseTool] | None = None,
    output_schema: type[BaseModel] | None = None,
    conversational: bool = False,
    context_instruction: Callable[[ReadonlyContext], str | Awaitable[str]] | None = None,
    max_output_tokens: int = 4096,
    retry_attempts: int = 0,
) -> LlmAgent:
    prompt = (PROMPT_DIR / definition.prompt_file).read_text(encoding="utf-8")

    async def instruction(context: ReadonlyContext) -> str:
        extra = context_instruction(context) if context_instruction else ""
        if inspect.isawaitable(extra):
            extra = await extra
        return prompt + ("\n\n" + extra if extra else "")

    return LlmAgent(
        name=definition.name,
        description=definition.description,
        model=model,
        instruction=instruction if context_instruction else prompt,
        tools=tools or [],
        output_schema=output_schema,
        output_key=f"{definition.name}_output" if output_schema else None,
        include_contents="default" if conversational else "none",
        generate_content_config=types.GenerateContentConfig(
            max_output_tokens=max_output_tokens,
            http_options=retrying(retry_attempts) if retry_attempts > 1 else None,
        ),
    )
