"""Register a vertical here; session/HTTP code does not need a new implementation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from google.adk.agents import LlmAgent

from app.agents.food_agent import create_food_chat_agent
from app.agents.stylist_agent import create_stylist_agent
from app.config import Settings
from app.schemas import Profile


@dataclass(frozen=True)
class AgentRegistration:
    key: str
    display_name: str
    # factory(settings, services): services are app-level adapters (e.g. look storage)
    # shared by all users; user state lives only in sessions and the Store.
    factory: Callable[[Settings, Any], LlmAgent]
    enabled: Callable[[Settings], bool]
    capabilities: Callable[[Settings], list[str]]
    profile_context: Callable[[Profile], dict]
    max_llm_calls: Callable[[Settings], int] = lambda settings: settings.agent_max_llm_calls
    timeout_seconds: Callable[[Settings], int] = lambda settings: settings.agent_timeout_seconds
    accepts_images: bool = False
    default_title: str = "New conversation"

    @property
    def app_name(self) -> str:
        return f"intentcart_{self.key}"


def stylist_capabilities(settings: Settings) -> list[str]:
    capabilities = ["look_board", "reference_images"]
    if settings.stylist_search_enabled:
        capabilities += ["google_search", "product_discovery", "inspiration"]
    if settings.stylist_images_enabled:
        capabilities.append("concept_images")
    if settings.stylist_maps_enabled:
        capabilities.append("local_boutiques")
    return capabilities


AGENTS = {
    "stylist": AgentRegistration(
        key="stylist",
        display_name="Shop a look",
        factory=create_stylist_agent,
        enabled=lambda settings: settings.stylist_mode == "gemini",
        capabilities=stylist_capabilities,
        profile_context=lambda profile: {
            "country": profile.country,
            "style": profile.style.model_dump(),
        },
        max_llm_calls=lambda settings: settings.stylist_max_llm_calls,
        timeout_seconds=lambda settings: settings.stylist_timeout_seconds,
        accepts_images=True,
        default_title="New look",
    ),
    "food": AgentRegistration(
        key="food",
        display_name="Food companion",
        factory=lambda settings, services: create_food_chat_agent(settings),
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
        default_title="New review",
    ),
}
