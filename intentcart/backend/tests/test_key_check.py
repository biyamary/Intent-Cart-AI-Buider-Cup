from unittest.mock import MagicMock

import pytest
from google.genai.errors import ClientError

from scripts import check_google_key


@pytest.fixture
def key_check(monkeypatch):
    settings = check_google_key.KeyCheckSettings(
        _env_file=None, google_api_key="synthetic-secret-key", gemini_model="gemini-test"
    )
    monkeypatch.setattr(check_google_key, "KeyCheckSettings", lambda: settings)
    factory = MagicMock()
    client = factory.return_value.__enter__.return_value
    client.models.list.return_value = [object()]
    client.models.generate_content.return_value.text = "OK"
    monkeypatch.setattr(check_google_key.genai, "Client", factory)
    return settings, factory, client


def test_auth_only_does_not_generate(key_check, capsys):
    _, factory, client = key_check
    assert check_google_key.main(["--auth-only"]) == 0
    client.models.generate_content.assert_not_called()
    assert factory.call_args.kwargs["http_options"].retry_options.attempts == 1
    assert "synthetic-secret-key" not in capsys.readouterr().out


@pytest.mark.parametrize("status,method", [(403, "list"), (429, "generate_content")])
def test_authentication_failure_is_separate_from_generation_failure(
    key_check, capsys, status, method
):
    _, _, client = key_check
    getattr(client.models, method).side_effect = ClientError(
        status, {"error": {"message": "synthetic-secret-key"}}
    )
    assert check_google_key.main([]) == 1
    output = capsys.readouterr().out
    assert f"HTTP {status}" in output
    assert "synthetic-secret-key" not in output
    if status == 403:
        client.models.generate_content.assert_not_called()
        assert "PASS:" not in output
    else:
        assert "PASS: Gemini accepted the key" in output
        assert "does not mean the key is invalid" in output


def test_success_and_missing_key(key_check, capsys):
    settings, factory, client = key_check
    assert check_google_key.main([]) == 0
    assert "Reply: OK" in capsys.readouterr().out
    assert "tools" not in client.models.generate_content.call_args.kwargs
    settings.google_api_key = check_google_key.SecretStr("")
    factory.reset_mock()
    assert check_google_key.main([]) == 1
    factory.assert_not_called()
    assert "missing or empty" in capsys.readouterr().out
