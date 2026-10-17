"""The only place that selects Gemini models and loads prompt placeholders."""

from pathlib import Path

from google.adk.agents import LlmAgent
from pydantic import BaseModel

from app.config import Settings

PROMPT_DIR = Path(__file__).with_name("prompts")


def build_agent(
    name: str, prompt_file: str, schema: type[BaseModel], settings: Settings, *, lite=False
) -> LlmAgent:
    return LlmAgent(
        name=name,
        model=settings.gemini_lite_model if lite else settings.gemini_model,
        instruction=(PROMPT_DIR / prompt_file).read_text(encoding="utf-8"),
        output_schema=schema,
        output_key=f"{name}_output",
        include_contents="none",
    )
