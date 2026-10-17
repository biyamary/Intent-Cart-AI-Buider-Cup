import httpx
import pytest
from google.genai.errors import ClientError

from app.agents.errors import describe_agent_error


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
