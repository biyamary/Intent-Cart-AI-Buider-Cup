"""Check Gemini authentication and generation independently of the application.

From backend/:
    uv run python scripts/check_google_key.py
    uv run python scripts/check_google_key.py --auth-only

Reads GOOGLE_API_KEY and GEMINI_MODEL from backend/.env or the environment.
Never prints the key, raw provider errors, or exception tracebacks.
"""

import argparse
import logging
import os
from pathlib import Path

from google import genai
from google.genai import errors, types
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class KeyCheckSettings(BaseSettings):
    # Only these two fields matter; Firebase and agent settings are irrelevant.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        extra="ignore",
        hide_input_in_errors=True,
    )
    google_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-flash-latest"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--auth-only", action="store_true", help="Only list one model; do not generate text."
    )
    args = parser.parse_args(argv)
    previous_log_level = logging.root.manager.disable
    # HTTP/SDK debug logs can contain credential-bearing URLs.
    logging.disable(logging.CRITICAL)
    try:
        return check_key(auth_only=args.auth_only)
    finally:
        logging.disable(previous_log_level)


def check_key(*, auth_only: bool) -> int:
    try:
        settings = KeyCheckSettings()
    except ValidationError:
        print("FAIL: Could not load GOOGLE_API_KEY / GEMINI_MODEL. Check backend/.env.")
        return 1
    api_key = settings.google_api_key.get_secret_value().strip()
    if not api_key:
        print("FAIL: GOOGLE_API_KEY is missing or empty. Set it in backend/.env.")
        return 1
    source = (
        "process environment (overrides .env)" if "GOOGLE_API_KEY" in os.environ else "backend/.env"
    )
    print(f"Key source: {source}; key value hidden.")
    print(f"Model: {settings.gemini_model}")
    stage = "authentication / model listing"
    try:
        with genai.Client(
            api_key=api_key,
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=20000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        ) as client:
            print("Checking authentication...")
            # Fetch at most one page, rather than iterating through the catalog.
            next(iter(client.models.list(config={"page_size": 1})), None)
            print("PASS: Gemini accepted the key for model listing.")
            if auth_only:
                print("Generation and model quota were not tested (--auth-only).")
                return 0
            stage = "text generation"
            print("Checking a minimal text request (no agent or Google Search)...")
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents="Reply with the single word OK.",
                config=types.GenerateContentConfig(max_output_tokens=128),
            )
            print("PASS: Gemini accepted the text generation request.")
            if response.text:
                print(f"Reply: {response.text.strip()[:160]}")
            else:
                print("No visible text returned; authentication and API request still succeeded.")
            return 0
    except errors.APIError as error:
        print(f"FAIL: {stage} returned HTTP {error.code}.")
        hints = {
            400: "The key or request was rejected. Check the key in AI Studio and the model setting.",
            401: "Authentication failed. Replace the key with a valid Gemini API key.",
            403: "Access denied. Check key restrictions, project permissions, and whether the key is blocked.",
            404: "The requested model or resource is unavailable. Check GEMINI_MODEL and model access.",
            429: "Quota or capacity is exhausted. Check this project's model limits in AI Studio. "
            "A 429 alone does not mean the key is invalid.",
        }
        print(
            hints.get(
                error.code, "Google returned a service error. Retry later or check its status page."
            )
        )
    except Exception as error:
        print(f"FAIL: {stage} could not complete ({type(error).__name__}).")
        print("Check network/proxy access and installed dependencies. Key validity is unconfirmed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
