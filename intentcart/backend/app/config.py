from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", extra="ignore", hide_input_in_errors=True
    )

    app_env: Literal["development", "test", "production"] = "development"
    agent_mode: Literal["demo", "gemini"] = "demo"
    food_research_enabled: bool = True
    food_research_max_gaps: int = Field(default=12, ge=1, le=40)
    food_cache_days: int = Field(default=30, ge=1, le=90)
    # Override conversational agents independently of global AGENT_MODE.
    stylist_agent_mode: Literal["demo", "gemini"] | None = None
    stylist_search_enabled: bool = False
    food_agent_mode: Literal["demo", "gemini"] | None = None
    food_search_enabled: bool = True
    agent_session_backend: Literal["memory", "sqlite"] = "sqlite"
    agent_session_db_path: Path = BACKEND_DIR / ".data" / "agent_sessions.db"
    agent_max_llm_calls: int = Field(default=6, ge=1, le=20)
    agent_max_conversation_turns: int = Field(default=40, ge=1, le=100)
    auth_mode: Literal["demo", "firebase"] = "demo"
    store_backend: Literal["memory", "firestore"] = "memory"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    google_api_key: SecretStr = SecretStr("")
    google_genai_use_vertexai: bool = False
    google_cloud_location: str = "global"
    gemini_model: str = "gemini-flash-latest"
    gemini_lite_model: str = "gemini-flash-lite-latest"
    agent_timeout_seconds: int = Field(default=60, ge=1, le=180)
    google_cloud_project: str = ""
    enable_open_food_facts: bool = False
    open_food_facts_user_agent: str = "IntentCart/0.1 (replace-with-your-contact)"
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    @model_validator(mode="after")
    def validate_modes(self):
        if self.app_env == "production" and (
            self.auth_mode == "demo" or self.store_backend == "memory"
        ):
            raise ValueError("Production requires Firebase auth and Firestore storage.")
        if "gemini" in (self.agent_mode, self.stylist_agent_mode, self.food_agent_mode):
            if self.google_genai_use_vertexai:
                if not self.google_cloud_project.strip() or not self.google_cloud_location.strip():
                    raise ValueError(
                        "Vertex AI requires GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION."
                    )
            elif not self.google_api_key.get_secret_value():
                raise ValueError("Gemini Developer API agents require GOOGLE_API_KEY.")
        if (
            self.auth_mode == "firebase" or self.store_backend == "firestore"
        ) and not self.google_cloud_project:
            raise ValueError("Firebase/Firestore requires GOOGLE_CLOUD_PROJECT.")
        if self.enable_open_food_facts and "replace-with" in self.open_food_facts_user_agent:
            raise ValueError("Set an identifying OPEN_FOOD_FACTS_USER_AGENT first.")
        return self

    @property
    def stylist_mode(self) -> Literal["demo", "gemini"]:
        return self.stylist_agent_mode or self.agent_mode

    @property
    def food_mode(self) -> Literal["demo", "gemini"]:
        return self.food_agent_mode or self.agent_mode


@lru_cache
def get_settings() -> Settings:
    return Settings()
