"""Shared construction policy; ADK's LlmAgent remains the actual base agent.

Use composition: each vertical owns its prompt and tools, while the application
owns sessions, identity, limits and transport. Never store user state on an agent.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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


def create_agent(
    definition: AgentDefinition,
    *,
    model: str,
    tools: list[BaseTool] | None = None,
    output_schema: type[BaseModel] | None = None,
    conversational: bool = False,
    context_instruction: Callable[[ReadonlyContext], str] | None = None,
) -> LlmAgent:
    prompt = (PROMPT_DIR / definition.prompt_file).read_text(encoding="utf-8")

    def instruction(context: ReadonlyContext) -> str:
        return prompt + ("\n\n" + context_instruction(context) if context_instruction else "")

    return LlmAgent(
        name=definition.name,
        description=definition.description,
        model=model,
        instruction=instruction if context_instruction else prompt,
        tools=tools or [],
        output_schema=output_schema,
        output_key=f"{definition.name}_output" if output_schema else None,
        include_contents="default" if conversational else "none",
        generate_content_config=types.GenerateContentConfig(max_output_tokens=4096),
    )
