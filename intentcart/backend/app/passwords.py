"""Salted scrypt password hashes for AUTH_MODE=static (standard library only).

Format: ``scrypt:<n>:<r>:<p>:<salt b64url>:<hash b64url>``. It contains no ``$`` so
shells and .env interpolation leave it intact.
"""

import base64
import hashlib
import hmac
import re
import secrets
from functools import lru_cache

N, R, P = 2**14, 8, 1
KEY_BYTES = 32
USERNAME = re.compile(r"[a-z0-9_-]{1,32}")
HASH = re.compile(r"scrypt:(\d+):(\d+):(\d+):([A-Za-z0-9_-]+):([A-Za-z0-9_-]+)")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, dklen=KEY_BYTES, maxmem=64 * 1024 * 1024
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt:{N}:{R}:{P}:{_b64(salt)}:{_b64(_derive(password, salt, N, R, P))}"


def valid_username(username: str) -> bool:
    return USERNAME.fullmatch(username) is not None


def valid_password_hash(encoded: str) -> bool:
    match = HASH.fullmatch(encoded)
    if not match:
        return False
    n, r, p = (int(value) for value in match.groups()[:3])
    # Accept only power-of-two work factors scrypt can run within the memory limit.
    return n >= 2**14 and n & (n - 1) == 0 and 128 * n * r <= 32 * 1024 * 1024 and 1 <= p <= 4


@lru_cache(maxsize=1)
def _decoy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


def verify_password(password: str, encoded: str | None) -> bool:
    """Constant-time check. Unknown users (`encoded=None`) cost the same work."""
    if encoded is None or not valid_password_hash(encoded):
        encoded, known = _decoy_hash(), False
    else:
        known = True
    n, r, p, salt, expected = HASH.fullmatch(encoded).groups()
    actual = _derive(password, _unb64(salt), int(n), int(r), int(p))
    return hmac.compare_digest(actual, _unb64(expected)) and known
