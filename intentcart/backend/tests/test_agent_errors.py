import httpx
import pytest
from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from google.auth.exceptions import TransportError as GoogleTransportError
from google.genai.errors import ClientError, ServerError

from app.agents.errors import StructuredResponseError, describe_agent_error


def quota_error(*, quota_id="GenerateRequestsPerMinutePerProjectPerModel-FreeTier", value=None):
    violation = {"quotaId": quota_id, "subject": "private-project", "description": "private-key"}
    if value is not None:
        violation["quotaValue"] = value
    return ClientError(
        429,
        {
            "error": {
                "message": "private-key private-project",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [violation],
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12.3s"},
                ],
            }
        },
    )


@pytest.mark.parametrize("zero", [0, "0"])
def test_zero_quota_overrides_short_retry_delay(zero):
    failure = describe_agent_error(quota_error(value=zero))
    assert failure.reason == "quota_zero"
    assert failure.retry_after is None
    assert failure.retryable is False
    assert "billing tier" in failure.detail
    assert "private-" not in repr(failure)


def test_daily_quota_overrides_short_retry_delay():
    failure = describe_agent_error(
        quota_error(quota_id="GenerateRequestsPerDayPerProjectPerModel-FreeTier", value="20")
    )
    assert failure.reason == "quota_daily"
    assert failure.retry_after is None
    assert "daily quota reset" in failure.detail


def test_temporary_quota_rounds_delay_up_and_redacts_provider_payload():
    failure = describe_agent_error(quota_error(value="10"))
    assert failure.reason == "quota_retry"
    assert failure.retry_after == 13
    assert "at least 13 seconds" in failure.detail
    assert "private-" not in repr(failure)


@pytest.mark.parametrize(
    "limit,reason", [("0", "quota_zero"), ("0.5", "quota_unspecified"), ("10", "quota_unspecified")]
)
def test_legacy_limit_message_is_classified_without_returning_it(limit, reason):
    failure = describe_agent_error(
        ClientError(
            429,
            {
                "error": {
                    "message": "private-key Quota exceeded for metric: "
                    f"generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: {limit}, model: private-model"
                }
            },
        )
    )
    assert failure.reason == reason
    assert "private-" not in repr(failure)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"error": None},
        {"error": {"details": None}},
        {
            "details": [
                None,
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": None},
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "secret"},
            ]
        },
    ],
)
def test_missing_or_malformed_metadata_keeps_actionable_generic_error(body):
    failure = describe_agent_error(ClientError(429, body))
    assert failure.status == 429
    assert failure.reason == "quota_unspecified"
    assert failure.retry_after is None
    assert "Google AI Studio" in failure.detail


def test_retry_after_header_without_rpc_details():
    response = httpx.Response(429, headers={"Retry-After": "30"})
    failure = describe_agent_error(ClientError(429, {}, response=response))
    assert failure.retry_after == 30


def test_conversation_failure_uses_supplied_agent_name_without_internal_detail():
    failure = describe_agent_error(TimeoutError("private timeout"), "The food companion")
    assert failure.reason == "timeout"
    assert failure.retryable is True
    assert failure.detail.startswith("The food companion took too long")
    assert "private" not in failure.detail


@pytest.mark.parametrize(
    "error,reason,status",
    [
        (
            ServerError(503, {"error": {"message": "private-provider-payload"}}),
            "provider_unavailable",
            503,
        ),
        (httpx.ConnectError("private endpoint"), "provider_connection", 502),
        (GoogleTransportError("private credentials path"), "provider_connection", 502),
        (StructuredResponseError("empty_response"), "empty_response", 502),
    ],
)
def test_transient_conversation_failures_are_specific_and_redacted(error, reason, status):
    failure = describe_agent_error(error, "The stylist")
    assert failure.reason == reason
    assert failure.status == status
    assert failure.retryable is True
    assert "private" not in repr(failure)


def test_step_limit_failure_suggests_a_narrower_question():
    failure = describe_agent_error(
        LlmCallsLimitExceededError("Max number of llm calls limit of `6` exceeded"),
        "The food companion",
    )
    assert failure.reason == "step_limit"
    assert failure.detail.startswith("The food companion needed more steps")
    assert "llm calls" not in failure.detail


def test_provider_retry_after_is_preserved_for_service_failure():
    response = httpx.Response(503, headers={"Retry-After": "7"})
    failure = describe_agent_error(ServerError(503, {}, response=response))
    assert failure.reason == "provider_unavailable"
    assert failure.retry_after == 7
