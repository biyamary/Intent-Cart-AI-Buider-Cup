import time

import pytest
from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE, issue_session, read_session
from app.config import Settings
from app.main import create_app
from app.passwords import hash_password, verify_password

JOHN_PASSWORD = "john-correct-horse"
JANE_PASSWORD = "jane-battery-staple"
USERS = {"john": hash_password(JOHN_PASSWORD), "jane": hash_password(JANE_PASSWORD)}
SECRET = "s" * 40


def static_settings(**overrides):
    values = {
        "app_env": "test",
        "agent_mode": "demo",
        "auth_mode": "static",
        "static_users": USERS,
        "auth_secret_key": SECRET,
        "store_backend": "memory",
        "agent_session_backend": "memory",
    }
    return Settings(_env_file=None, **(values | overrides))


@pytest.fixture
def static_client():
    with TestClient(create_app(static_settings())) as client:
        yield client


def login(client, username="john", password=JOHN_PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_password_hashes_are_salted_and_verified():
    assert USERS["john"] != hash_password(JOHN_PASSWORD)
    assert JOHN_PASSWORD not in USERS["john"]
    assert verify_password(JOHN_PASSWORD, USERS["john"])
    assert not verify_password(JANE_PASSWORD, USERS["john"])
    assert not verify_password(JOHN_PASSWORD, None)
    assert not verify_password(JOHN_PASSWORD, "plain-text-password")


def test_static_mode_requires_secret_and_hashed_users():
    with pytest.raises(ValueError):
        static_settings(auth_secret_key="short")
    with pytest.raises(ValueError):
        static_settings(static_users={})
    with pytest.raises(ValueError):
        static_settings(static_users={"john": JOHN_PASSWORD})


def test_public_and_protected_routes(static_client):
    assert static_client.get("/api/health").status_code == 200
    for path in ("/api/auth/me", "/api/profile", "/api/agents", "/api/agents/food/sessions"):
        assert static_client.get(path).status_code == 401, path
    assert static_client.delete("/api/agents/sessions").status_code == 401


def test_login_sets_http_only_cookie_and_logout_clears_it(static_client):
    response = login(static_client, "  John ")
    assert response.status_code == 200
    assert response.json() == {"id": "john", "name": "John", "auth_mode": "static"}
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    assert JOHN_PASSWORD not in response.text
    assert static_client.get("/api/auth/me").json()["id"] == "john"
    assert static_client.get("/api/profile").status_code == 200

    assert static_client.post("/api/auth/logout").status_code == 204
    assert static_client.get("/api/auth/me").status_code == 401


def test_wrong_password_unknown_user_and_other_users_password(static_client):
    assert login(static_client, "john", "wrong").status_code == 401
    assert login(static_client, "mallory", JOHN_PASSWORD).status_code == 401
    assert login(static_client, "john", JANE_PASSWORD).status_code == 401
    assert static_client.get("/api/auth/me").status_code == 401


def test_users_are_isolated(static_client):
    login(static_client)
    assert static_client.put("/api/profile", json={"allergies": ["milk"]}).status_code == 200
    login(static_client, "jane", JANE_PASSWORD)
    assert static_client.get("/api/auth/me").json()["id"] == "jane"
    assert static_client.get("/api/profile").json()["allergies"] == []


def test_forged_tampered_and_expired_cookies_are_rejected(static_client):
    settings = static_client.app.state.settings
    value, _ = issue_session(settings, "john")
    _, uid, expires, signature = value.split(".")
    forged = [
        f"v1.jane.{expires}.{signature}",  # swap user, keep john's signature
        f"v1.{uid}.{int(expires) + 999999}.{signature}",  # extend expiry
        f"v1.{uid}.{expires}.{'A' * len(signature)}",
        "v1.john.9999999999.",
        "john",
    ]
    for cookie in forged:
        static_client.cookies.set(SESSION_COOKIE, cookie, path="/api")
        assert static_client.get("/api/auth/me").status_code == 401, cookie
    expired, _ = issue_session(settings, "john", now=time.time() - 13 * 3600)
    assert read_session(settings, expired) is None
    assert read_session(settings, value) == "john"


def test_password_change_or_secret_rotation_revokes_cookies():
    value, _ = issue_session(static_settings(), "john")
    rotated = static_settings(auth_secret_key="t" * 40)
    changed = static_settings(static_users={**USERS, "john": hash_password("new-password-1")})
    assert read_session(rotated, value) is None
    assert read_session(changed, value) is None


def test_repeated_failures_are_throttled(static_client):
    for _ in range(5):
        assert login(static_client, "john", "wrong").status_code == 401
    locked = login(static_client)
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0
    # Another account is unaffected.
    assert login(static_client, "jane", JANE_PASSWORD).status_code == 200


def test_password_login_disabled_outside_static_mode(client):
    assert login(client).status_code == 404
    assert client.get("/api/auth/me").json()["id"] == "local-demo-user"
