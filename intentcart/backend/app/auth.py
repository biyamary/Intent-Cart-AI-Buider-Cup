import asyncio

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


async def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    settings = request.app.state.settings
    if settings.auth_mode == "demo":
        return "local-demo-user"
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
