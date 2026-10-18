"""Shared construction policy; ADK's LlmAgent remains the actual base agent.

Use composition: each vertical owns its prompt and tools, while the application
owns sessions, identity, limits and transport. Never store user state on an agent.
"""

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.llm_request import LlmRequest
from google.adk.tools import AgentTool, ToolContext
from google.adk.tools.base_tool import BaseTool
from google.genai import types
from pydantic import BaseModel

PROMPT_DIR = Path(__file__).with_name("prompts")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    prompt_file: str


def retrying(attempts: int) -> types.HttpOptions:
    """Back off and retry transient quota, connection and service errors."""
    return types.HttpOptions(
        retry_options=types.HttpRetryOptions(
            attempts=attempts,
            initial_delay=2,
            max_delay=15,
            http_status_codes=[429, 500, 502, 503, 504],
        )
    )


FINAL_CALL_NOTE = (
    "This is your last step for this reply: tools are now unavailable. Answer the user now "
    "from the evidence already gathered in this conversation, say plainly what you could not "
    "verify, and offer to look further if they ask a follow-up."
)
# Epoch seconds after which a conversational turn must answer without further tools.
ANSWER_BY_KEY = "temp:answer_by"


def answer_on_last_call(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """Turn off function calling once a run is out of model calls or time.

    Otherwise a turn that spends its budget on research ends in ADK's
    LlmCallsLimitExceededError or the turn timeout, and the user gets an error
    instead of an answer. ADK counts calls per invocation; AgentTool sub-agents
    run in their own.
    """
    if not any(tool.function_declarations for tool in llm_request.config.tools or []):
        return
    answer_by = callback_context.state.get(ANSWER_BY_KEY)
    out_of_time = isinstance(answer_by, (int, float)) and time.time() >= answer_by
    run_config = callback_context.run_config
    limit = run_config.max_llm_calls if run_config else 0
    calls_made = sum(
        1
        for event in callback_context.session.events
        if event.invocation_id == callback_context.invocation_id
        and event.author == callback_context.agent_name
        and event.content is not None
        and event.content.role == "model"
    )
    out_of_calls = limit > 0 and calls_made + 1 >= limit
    if not (out_of_time or out_of_calls):
        return
    llm_request.config.tool_config = types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.NONE
        )
    )
    llm_request.append_instructions([FINAL_CALL_NOTE])


class TimedAgentTool(AgentTool):
    """An AgentTool that gives up after `timeout` seconds instead of stalling the turn."""

    def __init__(self, agent: BaseAgent, timeout: float, **kwargs):
        super().__init__(agent=agent, **kwargs)
        self.timeout = timeout

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        try:
            async with asyncio.timeout(self.timeout):
                return await super().run_async(args=args, tool_context=tool_context)
        except TimeoutError:
            logger.warning("Agent tool timed out: tool=%s seconds=%s", self.name, self.timeout)
            return {
                "error": "This search took too long and was stopped. Answer from what you "
                "already have, or try one narrower search."
            }


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
    thinking_level: types.ThinkingLevel | None = None,
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
        before_model_callback=answer_on_last_call if conversational and tools else None,
        generate_content_config=types.GenerateContentConfig(
            max_output_tokens=max_output_tokens,
            http_options=retrying(retry_attempts) if retry_attempts > 1 else None,
            thinking_config=types.ThinkingConfig(thinking_level=thinking_level)
            if thinking_level
            else None,
        ),
    )
