"""The only place that selects Gemini models and loads prompt placeholders."""

from google.adk.agents import LlmAgent
from pydantic import BaseModel

from app.agents.base import AgentDefinition, create_agent
from app.config import Settings


def build_agent(
    name: str, prompt_file: str, schema: type[BaseModel], settings: Settings, *, lite=False
) -> LlmAgent:
    return create_agent(
        AgentDefinition(name=name, description=f"IntentCart {name} step", prompt_file=prompt_file),
        model=settings.gemini_lite_model if lite else settings.gemini_model,
        output_schema=schema,
    )
