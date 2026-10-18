"""Print STATIC_USERS / AUTH_SECRET_KEY lines for AUTH_MODE=static.

Usage (from backend/): uv run python scripts/hash_password.py john jane
Passwords are read without echo and never written anywhere except as hashes.
"""

import getpass
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.passwords import hash_password, valid_username

MIN_LENGTH = 12


def main(usernames: list[str]) -> int:
    if not usernames:
        print(__doc__)
        return 2
    users = {}
    for username in usernames:
        username = username.strip().lower()
        if not valid_username(username):
            print(f"Invalid username {username!r}: use a-z, 0-9, _ or -.", file=sys.stderr)
            return 2
        password = getpass.getpass(f"Password for {username}: ")
        if len(password) < MIN_LENGTH:
            print(f"Use at least {MIN_LENGTH} characters.", file=sys.stderr)
            return 2
        if getpass.getpass(f"Repeat password for {username}: ") != password:
            print("Passwords do not match.", file=sys.stderr)
            return 2
        users[username] = hash_password(password)
    print("\n# Add to backend/.env (or your deployment's secret environment):")
    print("AUTH_MODE=static")
    print(f"STATIC_USERS={json.dumps(users, separators=(',', ':'))}")
    print(f"AUTH_SECRET_KEY={secrets.token_urlsafe(48)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
