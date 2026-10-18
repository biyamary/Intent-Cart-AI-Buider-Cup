"""Translate provider failures without exposing SDK payloads or credentials."""

import math
import re
from dataclasses import dataclass

from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from google.auth.exceptions import GoogleAuthError
from google.auth.exceptions import TransportError as GoogleTransportError
from google.genai import types
from google.genai.errors import (
    ClientError,
    FunctionInvocationError,
    ServerError,
    UnknownApiResponseError,
    UnknownFunctionCallArgumentError,
    UnsupportedFunctionError,
)
from httpx import TransportError
from pydantic import ValidationError


@dataclass(frozen=True)
class AgentFailure:
    status: int
    detail: str
    reason: str
    retry_after: int | None = None
    retryable: bool = True
    diagnostic_id: str | None = None


class StructuredResponseError(Exception):
    """An application-owned response failure, with no model output attached."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def ensure_complete_response(response):
    if response.finish_reason == types.FinishReason.MAX_TOKENS:
        raise StructuredResponseError("response_truncated")
    blocked = {
        types.FinishReason.SAFETY,
        types.FinishReason.RECITATION,
        types.FinishReason.BLOCKLIST,
        types.FinishReason.PROHIBITED_CONTENT,
    }
    if response.finish_reason in blocked or response.error_code in blocked:
        raise StructuredResponseError("response_blocked")
    if response.error_code:
        raise StructuredResponseError("model_response_error")


def validate_step_response(callback_context, llm_response):
    # ADK can discard contentless responses or validate incomplete JSON before
    # yielding a public event. Inspect finish reasons before those operations.
    ensure_complete_response(llm_response)


def _quota_failure(error: ClientError) -> AgentFailure:
    payload = error.details if isinstance(error.details, dict) else {}
    payload = payload.get("error", payload)
    details = payload.get("details", []) if isinstance(payload, dict) else []
    violations = []
    retry_after = None
    for item in details if isinstance(details, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("@type") == "type.googleapis.com/google.rpc.QuotaFailure":
            items = item.get("violations", [])
            if isinstance(items, list):
                violations.extend(value for value in items if isinstance(value, dict))
        if item.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
            delay = item.get("retryDelay")
            if isinstance(delay, str) and re.fullmatch(r"\d{1,9}(?:\.\d{1,9})?s", delay):
                retry_after = max(retry_after or 1, math.ceil(float(delay[:-1])))

    # Some responses supply only an HTTP delay, without RPC details.
    if retry_after is None and error.response is not None:
        delay = error.response.headers.get("Retry-After", "")
        if re.fullmatch(r"\d{1,9}", delay):
            retry_after = max(1, int(delay))

    # Older Gemini responses put the enforced limit only in the message. Match
    # the specific quota phrase; never include the provider's text in output.
    zero_limit = any(str(item.get("quotaValue")) == "0" for item in violations)
    message = error.message if isinstance(error.message, str) else ""
    zero_limit |= bool(
        re.search(
            r"Quota exceeded for metric: generativelanguage\.googleapis\.com/[\w/]+, "
            r"limit: 0(?:\.0+)?(?=[,\s]|$)",
            message,
        )
    )
    if zero_limit:
        return AgentFailure(
            429,
            "Gemini reports a quota limit of zero for this model. The app owner needs to "
            "check the project's model access and billing tier in Google AI Studio "
            "or Google Cloud Console (Vertex AI). "
            "Retrying immediately will not resolve a zero quota.",
            "quota_zero",
            retryable=False,
        )

    quota_ids = [str(item.get("quotaId", "")).lower() for item in violations]
    if any("perday" in quota_id for quota_id in quota_ids):
        # A short RetryInfo delay does not override an exhausted daily allowance.
        return AgentFailure(
            429,
            "Gemini's daily quota for this model is exhausted. Wait for the daily quota "
            "reset, or ask the app owner to review the project's limits in Google AI Studio "
            "or Google Cloud Console (Vertex AI).",
            "quota_daily",
        )
    if retry_after is not None:
        return AgentFailure(
            429,
            f"Gemini is limiting requests. Wait at least {retry_after} seconds before sending "
            "a follow-up. If this continues, the app owner should check the project's model "
            "quota in Google AI Studio or Google Cloud Console (Vertex AI).",
            "quota_retry",
            retry_after,
        )
    return AgentFailure(
        429,
        "Gemini could not accept this request because of a quota or capacity limit. "
        "Try again later. If this continues, the app owner should check this model's "
        "limits and billing tier in Google AI Studio or Google Cloud Console (Vertex AI). "
        "Starting a new chat does not reset the quota.",
        "quota_unspecified",
    )


def _adc_failure() -> AgentFailure:
    return AgentFailure(
        502,
        "Google Cloud authentication failed. For local Vertex AI, run "
        "gcloud auth application-default login and set the ADC quota project to "
        "GOOGLE_CLOUD_PROJECT. Verify that the account has access to that project.",
        "provider_auth",
        retryable=False,
    )


def _provider_retry_after(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    if response is None:
        return None
    delay = response.headers.get("Retry-After", "")
    return max(1, int(delay)) if re.fullmatch(r"\d{1,9}", delay) else None


def describe_agent_error(error: Exception, subject: str = "The assistant") -> AgentFailure:
    if isinstance(error, (GoogleTransportError, TransportError)):
        return AgentFailure(
            502,
            "The server temporarily lost its connection to Gemini. Your conversation and any "
            "completed planning steps are saved; please retry.",
            "provider_connection",
        )
    if isinstance(error, GoogleAuthError):
        return _adc_failure()
    if isinstance(error, LlmCallsLimitExceededError):
        return AgentFailure(
            502,
            f"{subject} needed more steps than one reply allows. Your conversation is saved; "
            "try a narrower question, such as one product or flavour.",
            "step_limit",
        )
    if isinstance(error, TimeoutError):
        return AgentFailure(
            504,
            f"{subject} took too long to reply. Your conversation is saved; send a follow-up to continue.",
            "timeout",
        )
    if isinstance(error, ClientError) and error.code == 429:
        return _quota_failure(error)
    if isinstance(error, ServerError) or (
        isinstance(error, ClientError) and isinstance(error.code, int) and error.code >= 500
    ):
        retry_after = _provider_retry_after(error)
        return AgentFailure(
            503,
            "Gemini was temporarily unavailable. Your conversation and any completed planning "
            "steps are saved; please retry in a moment.",
            "provider_unavailable",
            retry_after=retry_after,
        )
    if isinstance(error, ClientError) and error.code in {400, 401, 403, 404}:
        return AgentFailure(
            502,
            "Gemini could not start this request. Check the server's credentials, project "
            "permissions, enabled API, model access and Google Search support.",
            "provider_configuration",
            retryable=False,
        )
    if isinstance(
        error,
        (FunctionInvocationError, UnknownFunctionCallArgumentError, UnsupportedFunctionError),
    ):
        return AgentFailure(
            502,
            f"{subject} could not complete one of the requested actions. Any completed planning "
            "steps are saved; please retry.",
            "tool_protocol_failure",
        )
    if isinstance(error, UnknownApiResponseError):
        return AgentFailure(
            502,
            "Gemini returned an unreadable response. Your conversation and any completed planning "
            "steps are saved; please retry.",
            "invalid_provider_response",
        )
    if isinstance(error, StructuredResponseError):
        messages = {
            "empty_response": "Gemini returned no readable reply. Any completed planning steps are saved; please retry.",
            "response_truncated": "Gemini reached its output limit before completing the reply. Please retry with a shorter request.",
            "response_blocked": "Gemini did not return a reply for this request. Try rephrasing it.",
            "model_response_error": "Gemini reported an error instead of a completed reply. Please retry.",
        }
        if error.reason in messages:
            return AgentFailure(502, messages[error.reason], error.reason)
    return AgentFailure(
        502,
        f"{subject} could not complete that reply. Your conversation is saved; please try again.",
        "provider_failure",
    )


def describe_step_error(error: Exception) -> AgentFailure:
    """Actionable errors for extraction/research/report steps; never echo provider text."""
    if isinstance(error, GoogleAuthError):
        return _adc_failure()
    if isinstance(error, TimeoutError):
        return AgentFailure(
            504, "Gemini took too long to complete this step. Please retry.", "timeout"
        )
    if isinstance(error, ClientError):
        if error.code == 429:
            return _quota_failure(error)
        details = {
            400: (
                (
                    "Gemini rejected the request. For a photo, try re-exporting it as JPEG or PNG. "
                    "The server's model and request configuration may also need review."
                ),
                "provider_request",
            ),
            401: (
                (
                    "Gemini authentication failed. Check Application Default Credentials "
                    "for Vertex AI, or GOOGLE_API_KEY for the Gemini Developer API."
                ),
                "provider_auth",
            ),
            403: (
                (
                    "Gemini denied access. Check project permissions, API enablement and "
                    "any API key restrictions."
                ),
                "provider_access",
            ),
            404: (
                "The configured Gemini model or resource is unavailable. Check GEMINI_MODEL and project access.",
                "provider_model",
            ),
        }
        if error.code in details:
            detail, reason = details[error.code]
            return AgentFailure(502, detail, reason)
    if isinstance(error, ValidationError):
        return AgentFailure(
            502,
            "Gemini returned incomplete or invalid structured data. Please retry; for a photo, "
            "try a clearer crop of the ingredient label.",
            "invalid_response",
        )
    if isinstance(error, StructuredResponseError):
        messages = {
            "empty_response": "Gemini returned no readable answer. Please retry; for a photo, try a clearer label image.",
            "response_truncated": "Gemini reached its output limit before completing the response. Please retry with a smaller label crop or fewer ingredients.",
            "response_blocked": "Gemini did not return an answer for this request. Try a label-only photo or enter the ingredients as text.",
            "model_response_error": "Gemini reported an error instead of a completed answer. Please retry.",
        }
        if error.reason in messages:
            return AgentFailure(502, messages[error.reason], error.reason)
    if isinstance(error, TransportError):
        return AgentFailure(
            502,
            "The server could not reach Gemini. Check network access and retry.",
            "provider_connection",
        )
    return AgentFailure(
        502,
        "The assistant could not complete this step. Please retry. The server log contains "
        "a diagnostic category for the app owner.",
        "provider_failure",
    )
