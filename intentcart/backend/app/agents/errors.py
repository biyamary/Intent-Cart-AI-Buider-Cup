"""Translate provider failures without exposing SDK payloads or credentials."""

import math
import re
from dataclasses import dataclass

from google.genai.errors import ClientError


@dataclass(frozen=True)
class AgentFailure:
    status: int
    detail: str
    reason: str
    retry_after: int | None = None


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
            "check the API project's model access and billing tier in Google AI Studio. "
            "Retrying immediately will not resolve a zero quota.",
            "quota_zero",
        )

    quota_ids = [str(item.get("quotaId", "")).lower() for item in violations]
    if any("perday" in quota_id for quota_id in quota_ids):
        # A short RetryInfo delay does not override an exhausted daily allowance.
        return AgentFailure(
            429,
            "Gemini's daily quota for this model is exhausted. Wait for the daily quota "
            "reset, or ask the app owner to review the project's limits in Google AI Studio.",
            "quota_daily",
        )
    if retry_after is not None:
        return AgentFailure(
            429,
            f"Gemini is limiting requests. Wait at least {retry_after} seconds before sending "
            "a follow-up. If this continues, the app owner should check the project's model "
            "quota in Google AI Studio.",
            "quota_retry",
            retry_after,
        )
    return AgentFailure(
        429,
        "Gemini could not accept this request because of a quota or capacity limit. "
        "Try again later. If this continues, the app owner should check this model's "
        "limits and billing tier for the API key's project in Google AI Studio. "
        "Starting a new chat does not reset the quota.",
        "quota_unspecified",
    )


def describe_agent_error(error: Exception) -> AgentFailure:
    if isinstance(error, TimeoutError):
        return AgentFailure(
            504,
            "The stylist took too long to reply. Your conversation is saved; send a follow-up to continue.",
            "timeout",
        )
    if isinstance(error, ClientError) and error.code == 429:
        return _quota_failure(error)
    if isinstance(error, ClientError) and error.code in {400, 401, 403, 404}:
        return AgentFailure(
            502,
            "Gemini could not start this request. Check the server's API key, model access and Google Search support.",
            "provider_configuration",
        )
    return AgentFailure(
        502,
        "The stylist could not complete that reply. Your conversation is saved; please try again.",
        "provider_failure",
    )
