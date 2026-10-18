"""Keep ADK and direct Gemini requests on the same configured backend."""

import os

from google import genai
from google.genai import types

from app.config import Settings


def configure_adk_environment(settings: Settings) -> None:
    # ADK constructs its own Gen AI clients from the process environment.
    enabled = "true" if settings.google_genai_use_vertexai else "false"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = enabled
    # Newer SDK releases give this alias precedence over USE_VERTEXAI.
    os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = enabled
    if settings.google_genai_use_vertexai:
        os.environ["GOOGLE_CLOUD_PROJECT"] = settings.google_cloud_project
        os.environ["GOOGLE_CLOUD_LOCATION"] = settings.google_cloud_location
        # Full Vertex AI uses ADC; stale keys must not select express mode.
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)
    else:
        os.environ["GOOGLE_API_KEY"] = settings.google_api_key.get_secret_value()


def create_genai_client(
    settings: Settings, *, http_options: types.HttpOptions | None = None
) -> genai.Client:
    if settings.google_genai_use_vertexai:
        return genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            http_options=http_options,
        )
    return genai.Client(
        vertexai=False,
        api_key=settings.google_api_key.get_secret_value(),
        http_options=http_options,
    )
