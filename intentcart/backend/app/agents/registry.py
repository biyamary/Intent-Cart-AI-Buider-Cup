"""Register a vertical here; session/HTTP code does not need a new implementation."""

from dataclasses import dataclass
from typing import Callable

from google.adk.agents import LlmAgent

from app.agents.food_agent import create_food_chat_agent
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
    "food": AgentRegistration(
        key="food",
        display_name="Food companion",
        factory=create_food_chat_agent,
        enabled=lambda settings: settings.food_mode == "gemini",
        capabilities=lambda settings: (
            ["google_search", "web_fetch"]
            if settings.food_search_enabled
            else ["web_fetch"]
        ),
        profile_context=lambda profile: {
            "country": profile.country,
            "allergies": profile.allergies,
            "age_group": profile.age_group,
            "diet": profile.diet,
            "food_countries": profile.food_countries,
        },
    ),
}
