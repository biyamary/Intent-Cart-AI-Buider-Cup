"""Exercise the real ADK image handoff with a fake provider; no external calls."""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.genai.errors import ClientError

from app.agents.food_agent import create_extraction_agent
from app.agents.runtime import AgentRuntime
from app.agents.schemas import ExtractedLabel
from app.config import Settings


def run_with_model(model):
    settings = Settings(_env_file=None, agent_mode="gemini", google_api_key="synthetic-key")
    agent = create_extraction_agent(settings)
    agent.model = model
    return asyncio.run(
        AgentRuntime(settings).run(
            agent,
            "synthetic-user",
            {"task": "extract_label"},
            ExtractedLabel,
            image=b"synthetic-image-bytes",
            mime="image/png",
        )
    )


def test_current_turn_image_and_schema_reach_provider():
    class Model(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            parts = [p for c in llm_request.contents for p in (c.parts or [])]
            image = next(p.inline_data for p in parts if p.inline_data)
            assert image.data == b"synthetic-image-bytes"
            assert image.mime_type == "image/png"
            assert llm_request.config.response_schema or llm_request.config.response_json_schema
            assert any(p.text and "extract_label" in p.text for p in parts)
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text='{"product_name":"Test label","ingredients":["milk","sugar"],"contains":["milk"],"may_contain":["peanuts"]}'
                        )
                    ],
                )
            )

    result = run_with_model(Model(model="fake-provider"))
    assert result.ingredients == ["milk", "sugar"]
    assert result.contains == ["milk"]
    assert result.may_contain == ["peanuts"]


@pytest.mark.parametrize(
    "code,reason",
    [
        (400, "provider_request"),
        (401, "provider_auth"),
        (403, "provider_access"),
        (404, "provider_model"),
        (429, "quota_retry"),
    ],
)
def test_provider_errors_have_diagnostics_without_sensitive_payloads(code, reason, caplog):
    class Model(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            raise ClientError(
                code,
                {
                    "error": {
                        "message": "sensitive-key sensitive-image sensitive-label",
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                "retryDelay": "8s",
                            }
                        ],
                    }
                },
            )
            yield  # Make this method an async generator like the provider interface.

    with (
        caplog.at_level(logging.WARNING, logger="app.agents.runtime"),
        pytest.raises(HTTPException) as caught,
    ):
        run_with_model(Model(model="fake-provider"))
    assert caught.value.status_code == (429 if code == 429 else 502)
    assert f"reason={reason}" in caplog.text
    assert "sensitive-" not in caught.value.detail
    assert "sensitive-" not in caplog.text
    if code == 429:
        assert caught.value.headers == {"Retry-After": "8"}


@pytest.mark.parametrize(
    "response,reason",
    [
        (
            LlmResponse(
                content=types.Content(
                    role="model", parts=[types.Part.from_text(text="not JSON sensitive-label")]
                )
            ),
            "invalid_response",
        ),
        (LlmResponse(), "empty_response"),
        (LlmResponse(finish_reason=types.FinishReason.MAX_TOKENS), "response_truncated"),
        (LlmResponse(error_code="SAFETY", error_message="sensitive-label"), "response_blocked"),
    ],
)
def test_invalid_and_empty_responses_are_distinguished(response, reason, caplog):
    class Model(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            yield response

    with (
        caplog.at_level(logging.WARNING, logger="app.agents.runtime"),
        pytest.raises(HTTPException) as caught,
    ):
        run_with_model(Model(model="fake-provider"))
    assert caught.value.status_code == 502
    assert f"reason={reason}" in caplog.text
    assert "sensitive-" not in caught.value.detail
    assert "sensitive-" not in caplog.text


def test_photo_route_requires_confirmation_and_handles_unreadable_image(client):
    runtime = AsyncMock(
        return_value=ExtractedLabel(
            product_name="Test label",
            ingredients=["milk", "sugar"],
            may_contain=["peanuts"],
        )
    )
    client.app.state.agents.run = runtime
    response = client.post(
        "/api/food/extract/photo",
        files={"image": ("label.png", b"synthetic-image-bytes", "image/png")},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "awaiting_confirmation"
    assert response.json()["report"] is None
    assert runtime.await_args.kwargs["image"] == b"synthetic-image-bytes"
    assert runtime.await_args.kwargs["mime"] == "image/png"
    runtime.return_value = ExtractedLabel(
        product_name="Unknown", ingredients=[], needs_clearer_image=True
    )
    assert (
        client.post(
            "/api/food/extract/photo", files={"image": ("label.png", b"blank", "image/png")}
        ).status_code
        == 422
    )
