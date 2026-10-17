"""Register a vertical here; session/HTTP code does not need a new implementation."""

from dataclasses import dataclass
from typing import Callable

from google.adk.agents import LlmAgent

from app.agents.stylist_agent import create_stylist_agent
from app.config import Settings
from app.schemas import Profile


@dataclass(frozen=True)
class AgentRegistration:
    key: str
    display_name: str
    factory: Callable[[Settings], LlmAgent]
    enabled: Callable[[Settings], bool]
    capabilities: Callable[[Settings], list[str]]
    profile_context: Callable[[Profile], dict]

    @property
    def app_name(self) -> str:
        return f"intentcart_{self.key}"


AGENTS = {
    "stylist": AgentRegistration(
        key="stylist",
        display_name="Shop a look",
        factory=create_stylist_agent,
        enabled=lambda settings: settings.stylist_mode == "gemini",
        capabilities=lambda settings: ["google_search"] if settings.stylist_search_enabled else [],
        profile_context=lambda profile: {
            "country": profile.country,
            "style": profile.style.model_dump(),
        },
    ),
}
# Food's existing structured pipeline stays in food_agent.py. Register its
# conversational entry point here once its prompt and tools are implemented.
