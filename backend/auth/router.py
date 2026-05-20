"""FastAPI router for authentication endpoints (login, refresh, register, change-password)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .authentication import (
    create_access_token,
    create_refresh_token,
    get_current_subject,
    get_current_subject_allow_password_change,
    refresh_access_token,
)
from .hashing import verify_password
from .storage import (
    create_initial_user,
    ensure_default_admin,
    get_user_and_secret,
    is_initialized,
    requires_password_change,
    revoke_user_refresh_tokens,
    update_password,
)

router = APIRouter()


# ── Request models ──────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str = ""
    new_password: str = Field(..., min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    must_change_password: bool


# ── Endpoints ───────────────────────────────────────────────────────


@router.get("/auth/status")
async def auth_status():
    return {
        "initialized": is_initialized(),
        "requires_password_change": requires_password_change("zopedia") if is_initialized() else False,
        "auth_disabled": False,
    }


@router.post("/auth/login")
async def auth_login(body: LoginRequest):
    record = get_user_and_secret(body.username)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    salt, pwd_hash, _jwt_secret, must_change = record
    if not verify_password(body.password, salt, pwd_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    access_token = create_access_token(subject=body.username)
    refresh_token = create_refresh_token(subject=body.username)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        must_change_password=must_change,
    )


@router.post("/auth/refresh")
async def auth_refresh(body: dict):
    refresh_token = body.get("refresh_token", "")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required.",
        )
    access_token, username, is_desktop = refresh_access_token(refresh_token)
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        must_change_password=False,
    )


@router.post("/auth/change-password")
async def auth_change_password(
    body: ChangePasswordRequest,
    current_subject: str = Depends(get_current_subject_allow_password_change),
):
    record = get_user_and_secret(current_subject)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    salt, pwd_hash, _jwt_secret, must_change = record
    if not must_change and not verify_password(body.current_password, salt, pwd_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )
    update_password(current_subject, body.new_password)
    revoke_user_refresh_tokens(current_subject)
    access_token = create_access_token(subject=current_subject)
    refresh_token = create_refresh_token(subject=current_subject)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        must_change_password=False,
    )


@router.post("/auth/register")
async def auth_register(
    body: RegisterRequest,
    current_subject: str = Depends(get_current_subject),
):
    """Register a new user. Requires admin authentication."""
    # Only the default admin can create new users
    if current_subject != "zopedia":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can register new users.",
        )
    import secrets

    jwt_secret = secrets.token_urlsafe(64)
    try:
        create_initial_user(
            username=body.username,
            password=body.password,
            jwt_secret=jwt_secret,
            must_change_password=False,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User '{body.username}' already exists.",
        )
    return {"status": "ok", "username": body.username}
