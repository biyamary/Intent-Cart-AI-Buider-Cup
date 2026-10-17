from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    agent_mode: Literal["demo", "gemini"] = "demo"
    # Override only the conversational stylist while Food stays in demo mode.
    stylist_agent_mode: Literal["demo", "gemini"] | None = None
    stylist_search_enabled: bool = False
    agent_session_backend: Literal["memory", "sqlite"] = "sqlite"
    agent_session_db_path: Path = BACKEND_DIR / ".data" / "agent_sessions.db"
    agent_max_llm_calls: int = Field(default=6, ge=1, le=20)
    agent_max_conversation_turns: int = Field(default=40, ge=1, le=100)
    auth_mode: Literal["demo", "firebase"] = "demo"
    store_backend: Literal["memory", "firestore"] = "memory"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    google_api_key: SecretStr = SecretStr("")
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
        if (
            "gemini" in (self.agent_mode, self.stylist_agent_mode)
            and not self.google_api_key.get_secret_value()
        ):
            raise ValueError("Gemini agents require GOOGLE_API_KEY.")
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
