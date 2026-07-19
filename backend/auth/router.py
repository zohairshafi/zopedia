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
    create_api_key,
    create_initial_user,
    delete_user,
    ensure_default_admin,
    get_user_and_secret,
    get_user_display_name,
    get_user_permissions,
    is_admin_user,
    is_initialized,
    list_all_users,
    list_api_keys,
    requires_password_change,
    revoke_api_key,
    revoke_user_refresh_tokens,
    set_user_display_name,
    update_password,
    update_user_permissions,
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
    permissions: dict = {}


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
        permissions=get_user_permissions(body.username),
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
        permissions=get_user_permissions(username),
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
        permissions=get_user_permissions(current_subject),
    )


# ── Profile (self-service) ──────────────────────────────────────────


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(..., max_length=128)


@router.get("/auth/profile")
async def get_profile(current_subject: str = Depends(get_current_subject)):
    """Return the current user's profile (display name)."""
    return {
        "username": current_subject,
        "display_name": get_user_display_name(current_subject),
    }


@router.put("/auth/profile")
async def update_profile(
    body: UpdateProfileRequest,
    current_subject: str = Depends(get_current_subject),
):
    """Update the current user's display name."""
    display_name = body.display_name.strip()
    if not set_user_display_name(current_subject, display_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    return {"username": current_subject, "display_name": display_name}


@router.post("/auth/register")
async def auth_register(
    body: RegisterRequest,
    current_subject: str = Depends(get_current_subject),
):
    """Register a new user. Requires admin authentication."""
    # Only the default admin can create new users
    if not is_admin_user(current_subject):
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


# ── Admin user management ───────────────────────────────────────────


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field("", min_length=0)


@router.get("/auth/users")
async def admin_list_users(
    current_subject: str = Depends(get_current_subject),
):
    """List all users (admin only)."""
    if not is_admin_user(current_subject):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can list users.",
        )
    users = list_all_users()
    return {"users": users}


@router.post("/auth/users/{username}/reset-password")
async def admin_reset_password(
    username: str,
    body: AdminResetPasswordRequest,
    current_subject: str = Depends(get_current_subject),
):
    """Reset a user's password (admin only).  If *new_password* is empty
    a 4-word diceware passphrase is generated and returned."""
    if not is_admin_user(current_subject):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can reset passwords.",
        )

    record = get_user_and_secret(username)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found.",
        )

    new_password = body.new_password.strip()
    if not new_password:
        import diceware
        new_password = diceware.get_passphrase(
            options=diceware.handle_options(args=["-n", "4", "-d", "", "-c"])
        )

    update_password(username, new_password)
    revoke_user_refresh_tokens(username)
    return {"status": "ok", "username": username, "password": new_password}


class PermissionsUpdateRequest(BaseModel):
    can_save_chat_history: bool | None = None
    can_upload_files: bool | None = None
    is_admin: bool | None = None


@router.patch("/auth/users/{username}/permissions")
async def admin_update_permissions(
    username: str,
    body: PermissionsUpdateRequest,
    current_subject: str = Depends(get_current_subject),
):
    """Update a user's permissions (admin only). Accepts partial updates —
    only the fields provided are changed."""
    if not is_admin_user(current_subject):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can update permissions.",
        )

    record = get_user_and_secret(username)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found.",
        )

    # Merge with existing permissions
    current_perms = get_user_permissions(username)
    if body.can_save_chat_history is not None:
        current_perms["can_save_chat_history"] = body.can_save_chat_history
    if body.can_upload_files is not None:
        current_perms["can_upload_files"] = body.can_upload_files
    if body.is_admin is not None:
        current_perms["is_admin"] = body.is_admin

    update_user_permissions(username, current_perms)
    revoke_user_refresh_tokens(username)
    return {"status": "ok", "username": username, "permissions": current_perms}


@router.delete("/auth/users/{username}")
async def admin_delete_user(
    username: str,
    current_subject: str = Depends(get_current_subject),
):
    """Delete a user (admin only).  Cannot delete the admin account."""
    if not is_admin_user(current_subject):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin can delete users.",
        )
    if username == "zopedia":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the admin account.",
        )
    record = get_user_and_secret(username)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' not found.",
        )
    delete_user(username)
    revoke_user_refresh_tokens(username)
    return {"status": "ok", "username": username}


# ── API key management ──────────────────────────────────────────────


class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    expires_in_days: int | None = Field(None, ge=1)


class CreateApiKeyResponse(BaseModel):
    key: str
    api_key: dict


@router.get("/auth/api-keys")
async def auth_list_api_keys(
    current_subject: str = Depends(get_current_subject),
):
    """List all API keys for the authenticated user."""
    keys = list_api_keys(current_subject)
    return {"api_keys": keys}


@router.post("/auth/api-keys")
async def auth_create_api_key(
    body: CreateApiKeyRequest,
    current_subject: str = Depends(get_current_subject),
):
    """Create a new API key. The raw key is returned only once."""
    from datetime import datetime, timedelta, timezone

    expires_at: str | None = None
    if body.expires_in_days is not None:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)).isoformat()

    raw_key, row = create_api_key(current_subject, body.name.strip(), expires_at)
    return CreateApiKeyResponse(key=raw_key, api_key=row)


@router.delete("/auth/api-keys/{key_id}")
async def auth_revoke_api_key(
    key_id: int,
    current_subject: str = Depends(get_current_subject),
):
    """Revoke an API key belonging to the authenticated user."""
    if not revoke_api_key(current_subject, key_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found.",
        )
    return {"status": "ok"}
