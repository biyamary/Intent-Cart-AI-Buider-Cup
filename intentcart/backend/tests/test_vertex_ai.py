import sys

import pytest
from fastapi.testclient import TestClient
from google.adk.models.google_llm import Gemini
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from pydantic import ValidationError

from app.agents.errors import describe_agent_error, describe_step_error
from app.agents.google_client import configure_adk_environment, create_genai_client
from app.config import Settings
from app.main import create_app
from scripts import diagnose_gemini


@pytest.fixture(autouse=True)
def isolated_google_environment(monkeypatch):
    for key in (
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_GENAI_USE_ENTERPRISE",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def vertex_settings(**overrides):
    return Settings(
        _env_file=None,
        **(
            {
                "agent_mode": "gemini",
                "google_genai_use_vertexai": True,
                "google_cloud_project": "test-vertex-project",
                "google_cloud_location": "global",
                "agent_session_backend": "memory",
            }
            | overrides
        ),
    )


@pytest.mark.parametrize("mode", ["agent_mode", "stylist_agent_mode", "food_agent_mode"])
def test_vertex_accepts_adc_without_api_key_for_each_agent_mode(mode):
    settings = vertex_settings(**({"agent_mode": "demo", mode: "gemini"}))
    assert not settings.google_api_key.get_secret_value()


@pytest.mark.parametrize("missing", [{"google_cloud_project": ""}, {"google_cloud_location": " "}])
def test_vertex_requires_project_and_location(missing):
    with pytest.raises(ValidationError, match="Vertex AI requires"):
        vertex_settings(**missing)


def test_developer_api_still_requires_key():
    with pytest.raises(ValidationError, match="require GOOGLE_API_KEY"):
        Settings(_env_file=None, agent_mode="gemini")


def test_startup_routes_adk_to_vertex_even_with_stale_provider_environment(monkeypatch):
    settings = vertex_settings()
    monkeypatch.setenv("GOOGLE_API_KEY", "stale-api-key")
    monkeypatch.setenv("GEMINI_API_KEY", "another-stale-key")
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "false")
    with TestClient(create_app(settings)) as app_client:
        assert app_client.get("/api/health").status_code == 200
        with Gemini(model=settings.gemini_model).api_client as client:
            assert client.vertexai is True
            assert client._api_client.project == "test-vertex-project"
            assert client._api_client.location == "global"
            assert client._api_client.api_key is None


def test_switching_back_to_developer_api_overrides_vertex_environment():
    configure_adk_environment(vertex_settings())
    settings = Settings(_env_file=None, google_genai_use_vertexai=False, google_api_key="test-key")
    configure_adk_environment(settings)
    with Gemini(model=settings.gemini_model).api_client as client:
        assert client.vertexai is False
        assert client._api_client.api_key == "test-key"


def test_direct_client_uses_explicit_vertex_project_despite_stale_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "stale-key")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "false")
    with create_genai_client(vertex_settings()) as client:
        assert client.vertexai is True
        assert client._api_client.project == "test-vertex-project"
        assert client._api_client.location == "global"
        assert client._api_client.api_key is None


@pytest.mark.parametrize("error_type", [DefaultCredentialsError, RefreshError])
@pytest.mark.parametrize("describe", [describe_agent_error, describe_step_error])
def test_adc_errors_are_actionable_and_redacted(describe, error_type):
    failure = describe(error_type("private-token"))
    assert failure.reason == "provider_auth"
    assert "gcloud auth application-default login" in failure.detail
    assert "private-token" not in repr(failure)


def test_diagnostic_uses_vertex_without_key_and_can_check_lite_model(monkeypatch, capsys):
    from unittest.mock import MagicMock

    settings = vertex_settings(gemini_lite_model="gemini-lite-test")
    factory = MagicMock()
    monkeypatch.setattr(diagnose_gemini, "Settings", lambda: settings)
    monkeypatch.setattr(diagnose_gemini, "create_genai_client", factory)
    monkeypatch.setattr(sys, "argv", ["diagnose_gemini", "--lite"])
    assert diagnose_gemini.main() == 0
    client = factory.return_value.__enter__.return_value
    assert client.models.generate_content.call_args.kwargs["model"] == "gemini-lite-test"
    assert "authentication: ADC" in capsys.readouterr().out
