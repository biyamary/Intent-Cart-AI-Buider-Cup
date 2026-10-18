import asyncio
import base64
import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings

bearer = HTTPBearer(auto_error=False)

SESSION_COOKIE = "intentcart_session"
SESSION_VERSION = "v1"
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60


def _signature(settings: Settings, uid: str, expires: int) -> str:
    # The stored password hash is part of the message, so changing a password
    # (or AUTH_SECRET_KEY) invalidates every cookie issued before the change.
    message = f"{SESSION_VERSION}.{uid}.{expires}.{settings.static_users[uid]}".encode()
    key = settings.auth_secret_key.get_secret_value().encode()
    digest = hmac.new(key, message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def issue_session(settings: Settings, uid: str, now: float | None = None) -> tuple[str, int]:
    """Return a signed cookie value and its lifetime in seconds."""
    lifetime = settings.auth_session_hours * 3600
    expires = int(now if now is not None else time.time()) + lifetime
    return f"{SESSION_VERSION}.{uid}.{expires}.{_signature(settings, uid, expires)}", lifetime


def read_session(settings: Settings, value: str | None) -> str | None:
    """Return the user for a valid, unexpired cookie; never trust anything else."""
    if not value or len(value) > 256:
        return None
    parts = value.split(".")
    if len(parts) != 4 or parts[0] != SESSION_VERSION:
        return None
    _, uid, expires, signature = parts
    if uid not in settings.static_users or not expires.isdigit():
        return None
    if not hmac.compare_digest(signature, _signature(settings, uid, int(expires))):
        return None
    return uid if int(expires) > time.time() else None


class LoginThrottle:
    """Per-username failed-login limit. Single API worker, like turn execution."""

    def __init__(self):
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, key: str, now: float) -> deque[float]:
        failures = self._failures[key]
        while failures and failures[0] <= now - FAILURE_WINDOW_SECONDS:
            failures.popleft()
        return failures

    def retry_after(self, key: str) -> int | None:
        now = time.monotonic()
        failures = self._recent(key, now)
        if len(failures) < MAX_FAILURES:
            return None
        return max(1, int(failures[0] + FAILURE_WINDOW_SECONDS - now))

    def failed(self, key: str):
        self._recent(key, time.monotonic()).append(time.monotonic())

    def succeeded(self, key: str):
        self._failures.pop(key, None)


async def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    settings = request.app.state.settings
    if settings.auth_mode == "demo":
        return "local-demo-user"
    if settings.auth_mode == "static":
        uid = read_session(settings, request.cookies.get(SESSION_COOKIE))
        if uid is None:
            raise HTTPException(401, "Sign in to continue.")
        return uid
    if not credentials:
        raise HTTPException(401, "Sign in to continue.", headers={"WWW-Authenticate": "Bearer"})
    from firebase_admin import auth

    try:
        token = await asyncio.to_thread(
            auth.verify_id_token, credentials.credentials, check_revoked=True
        )
        uid = token["uid"]
        if "/" in uid:
            raise ValueError("Invalid user ID")
        return uid
    except Exception:
        raise HTTPException(401, "Invalid or expired sign-in token.") from None
