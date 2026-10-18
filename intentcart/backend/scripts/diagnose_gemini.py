"""One opt-in live request using the configured model and search setting.

From backend/: uv run python -m scripts.diagnose_gemini
Uses a fixed synthetic prompt, never reads conversations, and does not retry.
Pass --search to explicitly test Google Search regardless of the app setting.
"""

import argparse
import logging

from google.genai import types

from app.agents.errors import describe_agent_error
from app.agents.google_client import create_genai_client
from app.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--search", action="store_true", help="Explicitly test Google Search access."
    )
    parser.add_argument("--lite", action="store_true", help="Test GEMINI_LITE_MODEL instead.")
    args = parser.parse_args()
    # SDK debug logs can contain URLs. Print only application-owned diagnostics.
    previous_log_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        return diagnose(args)
    finally:
        logging.disable(previous_log_level)


def diagnose(args: argparse.Namespace) -> int:
    settings = Settings()
    search_enabled = args.search or settings.stylist_search_enabled
    model = settings.gemini_lite_model if args.lite else settings.gemini_model
    print(f"Configured model: {model}")
    if settings.google_genai_use_vertexai:
        print(f"Vertex AI project: {settings.google_cloud_project}")
        print(f"Vertex AI location: {settings.google_cloud_location}; authentication: ADC")
    else:
        print("Backend: Gemini Developer API; authentication: API key")
    print(f"Google Search enabled: {search_enabled}")
    if not settings.google_genai_use_vertexai and not settings.google_api_key.get_secret_value():
        print("Set GOOGLE_API_KEY in backend/.env first.")
        return 1
    try:
        with create_genai_client(
            settings,
            http_options=types.HttpOptions(
                timeout=20000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        ) as client:
            client.models.generate_content(
                model=model,
                contents="Reply with OK.",
                config=types.GenerateContentConfig(
                    max_output_tokens=128,
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                    if search_enabled
                    else None,
                ),
            )
    except Exception as error:  # noqa: BLE001 - never expose raw provider errors or credentials
        failure = describe_agent_error(error)
        print(f"Request failed: {failure.reason} (HTTP {failure.status})")
        print(failure.detail)
        return 1
    print("Gemini accepted the request with the selected capabilities.")
    print("Use scripts.smoke_stylist to verify a complete conversation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
