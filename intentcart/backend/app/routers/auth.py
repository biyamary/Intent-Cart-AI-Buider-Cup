import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import SESSION_COOKIE, current_user, issue_session
from app.passwords import verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SessionUser(BaseModel):
    id: str
    name: str
    auth_mode: str


def session_user(request: Request, uid: str) -> SessionUser:
    mode = request.app.state.settings.auth_mode
    name = "Demo user" if mode == "demo" else uid.title() if mode == "static" else "You"
    return SessionUser(id=uid, name=name, auth_mode=mode)


def set_cookie(request: Request, response: Response, value: str, max_age: int):
    response.set_cookie(
        SESSION_COOKIE,
        value,
        max_age=max_age,
        path="/api",
        httponly=True,
        secure=request.app.state.settings.secure_cookies,
        samesite="strict",
    )


@router.post("/login", response_model=SessionUser)
async def login(body: LoginRequest, request: Request, response: Response):
    settings = request.app.state.settings
    if settings.auth_mode != "static":
        raise HTTPException(404, "Password sign-in is not enabled.")
    username = body.username.strip().lower()
    known = username in settings.static_users
    # Unknown names share one bucket so guesses cannot grow the throttle table.
    throttle_key = username if known else "?"
    throttle = request.app.state.login_throttle
    if (wait := throttle.retry_after(throttle_key)) is not None:
        raise HTTPException(
            429,
            "Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(wait)},
        )
    valid = await asyncio.to_thread(
        verify_password, body.password, settings.static_users.get(username)
    )
    if not valid:
        throttle.failed(throttle_key)
        raise HTTPException(401, "Incorrect username or password.")
    throttle.succeeded(throttle_key)
    value, max_age = issue_session(settings, username)
    set_cookie(request, response, value, max_age)
    response.headers["Cache-Control"] = "no-store"
    return session_user(request, username)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    response.delete_cookie(
        SESSION_COOKIE,
        path="/api",
        httponly=True,
        secure=request.app.state.settings.secure_cookies,
        samesite="strict",
    )


@router.get("/me", response_model=SessionUser)
async def me(request: Request, response: Response, uid: str = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    return session_user(request, uid)
