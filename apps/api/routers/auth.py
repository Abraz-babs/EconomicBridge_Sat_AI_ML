"""Authentication endpoints — login, refresh, logout, activate, me.

Scope: the platform operator (super_admin) and registered tenant accounts
(tenant_admin). The public dashboard remains anonymous; these endpoints exist so
the admin panel and account-bound actions can be gated.

  POST /auth/login     {email, password}        → access + refresh + user
  POST /auth/refresh   {refresh_token}           → new access token
  POST /auth/logout    {refresh_token}           → revoke that session
  POST /auth/activate  {token, password}         → set first password, auto-login
  GET  /auth/me                                  → current user (Bearer)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from core.ratelimit import record_failure, reset as reset_ratelimit, too_many_failures
from core.security import (
    create_access_token,
    create_reset_token,
    decode_invite_token,
    decode_reset_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from db.engine import get_session
from dependencies import CurrentUser, get_current_user
from schemas.auth import (
    AccessData,
    ActivateRequest,
    AuthUser,
    ForgotAck,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenData,
)
from services.email import send_password_reset_email
from schemas.envelope import SuccessResponse, build_meta

router = APIRouter(prefix="/auth", tags=["auth"])

_UNAUTH = {"code": "UNAUTHENTICATED", "message": "Invalid credentials."}


async def _load_user(session: AsyncSession, *, user_id=None, email=None):
    if user_id is not None:
        q = text("SELECT id, org_id, email, password_hash, role, full_name, "
                 "is_active FROM public.users WHERE id = :v")
        v = user_id
    else:
        q = text("SELECT id, org_id, email, password_hash, role, full_name, "
                 "is_active FROM public.users WHERE email = :v")
        v = email
    return (await session.execute(q, {"v": v})).mappings().first()


async def _permitted_tenants(session: AsyncSession, org_id) -> list[str]:
    row = (await session.execute(
        text("SELECT permitted_tenants FROM public.organisations WHERE id = :o"),
        {"o": org_id},
    )).first()
    return list(row[0]) if row and row[0] else []


async def _org_tenant_slug(session: AsyncSession, org_id) -> str | None:
    """The registry tenant id of the user's own organisation (organisations.
    org_id — set to the tenant_registry id at onboarding). Drives which
    subscription the UI's module locks follow."""
    row = (await session.execute(
        text("SELECT org_id FROM public.organisations WHERE id = :o"),
        {"o": org_id},
    )).first()
    return row[0] if row else None


async def _issue_tokens(session: AsyncSession, user) -> TokenData:
    """Mint an access+refresh pair for `user` and persist the refresh hash."""
    s = get_settings()
    tenants = await _permitted_tenants(session, user["org_id"])
    access = create_access_token(
        user_id=user["id"], role=user["role"], org_id=user["org_id"],
        permitted_tenants=tenants,
    )
    raw_refresh, refresh_hash = new_refresh_token()
    expires = datetime.now(timezone.utc) + timedelta(days=s.jwt_refresh_ttl_days)
    await session.execute(
        text(
            """
            INSERT INTO public.refresh_tokens (user_id, token_hash, expires_at)
            VALUES (:uid, :h, :exp)
            """
        ),
        {"uid": user["id"], "h": refresh_hash, "exp": expires},
    )
    return TokenData(
        access_token=access,
        refresh_token=raw_refresh,
        user=AuthUser(
            id=user["id"], email=user["email"], role=user["role"],
            org_id=user["org_id"], full_name=user["full_name"],
            permitted_tenants=tenants,
            tenant_id=await _org_tenant_slug(session, user["org_id"]),
        ),
    )


def _client_key(request: Request) -> str:
    """IP-based rate-limit key. Behind the ALB the real client is the first hop
    in X-Forwarded-For; fall back to the socket peer."""
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else (
        request.client.host if request.client else "unknown")
    return f"login:{ip}"


@router.post("/login", response_model=SuccessResponse[TokenData])
async def login(
    body: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[TokenData]:
    # Brute-force guard: too many recent failures from this IP → 429.
    key = _client_key(request)
    blocked, retry = too_many_failures(key)
    if blocked:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED",
                    "message": f"Too many failed sign-in attempts. Try again in {retry}s."},
        )

    user = await _load_user(session, email=str(body.email).strip().lower())
    # Same 401 whether the email is unknown or the password is wrong — never
    # leak which accounts exist. verify_password is run regardless to keep the
    # timing roughly constant.
    ok = user is not None and verify_password(body.password, user["password_hash"])
    if not ok or not user["is_active"]:
        record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=_UNAUTH)

    reset_ratelimit(key)
    data = await _issue_tokens(session, user)
    await session.execute(
        text("UPDATE public.users SET last_login_at = NOW() WHERE id = :id"),
        {"id": user["id"]},
    )
    await session.commit()
    return SuccessResponse(data=data, meta=build_meta())


@router.post("/refresh", response_model=SuccessResponse[AccessData])
async def refresh(
    body: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[AccessData]:
    h = hash_token(body.refresh_token)
    row = (await session.execute(
        text(
            """
            SELECT user_id FROM public.refresh_tokens
             WHERE token_hash = :h AND revoked = false AND expires_at > NOW()
            """
        ),
        {"h": h},
    )).first()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail={"code": "UNAUTHENTICATED",
                                    "message": "Invalid or expired refresh token."})
    user = await _load_user(session, user_id=row[0])
    if user is None or not user["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=_UNAUTH)
    tenants = await _permitted_tenants(session, user["org_id"])
    access = create_access_token(
        user_id=user["id"], role=user["role"], org_id=user["org_id"],
        permitted_tenants=tenants,
    )
    return SuccessResponse(data=AccessData(access_token=access), meta=build_meta())


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    await session.execute(
        text(
            """
            UPDATE public.refresh_tokens
               SET revoked = true, revoked_at = NOW()
             WHERE token_hash = :h AND revoked = false
            """
        ),
        {"h": hash_token(body.refresh_token)},
    )
    await session.commit()


@router.post("/activate", response_model=SuccessResponse[TokenData])
async def activate(
    body: ActivateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[TokenData]:
    try:
        user_id = decode_invite_token(body.token)
    except JWTError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "INVITE_INVALID",
                                    "message": "Activation link is invalid or expired."}) from exc
    user = await _load_user(session, user_id=user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "INVITE_INVALID",
                                    "message": "Activation link is invalid or expired."})
    # Single-use: once the account is active the invite is spent.
    if user["is_active"]:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"code": "ALREADY_ACTIVE",
                                    "message": "This account is already active — please sign in."})
    await session.execute(
        text("UPDATE public.users SET password_hash = :p, is_active = true WHERE id = :id"),
        {"p": hash_password(body.password), "id": user_id},
    )
    user = await _load_user(session, user_id=user_id)  # reload with new state
    data = await _issue_tokens(session, user)
    await session.commit()
    return SuccessResponse(data=data, meta=build_meta())


@router.post("/forgot-password", response_model=SuccessResponse[ForgotAck])
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[ForgotAck]:
    """Email a short-lived reset link. ALWAYS returns the same 200 body —
    whether or not the address has an account — so the endpoint can never be
    used to enumerate users. Rate-limited per client IP via the same window
    as failed logins."""
    key = f"pwreset:{_client_key(request)}"
    blocked, _retry = too_many_failures(key)
    if blocked:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many reset requests. Please try again shortly.",
        )
    record_failure(key)  # every request spends a slot, hit or miss

    user = await _load_user(session, email=str(body.email).strip().lower())
    if user is not None and user["is_active"]:
        s = get_settings()
        reset_url = (
            f"{s.public_app_url}/reset?token={create_reset_token(user['id'])}"
        )
        send_password_reset_email(to=user["email"], reset_url=reset_url)
    return SuccessResponse(data=ForgotAck(), meta=build_meta())


@router.post("/reset-password", response_model=SuccessResponse[ForgotAck])
async def reset_password(
    body: ResetPasswordRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[ForgotAck]:
    """Set a new password from a valid reset token, then revoke every live
    session for the account (a reset after a suspected compromise must not
    leave old refresh tokens working). No auto-login — the user signs in
    with the new password."""
    try:
        user_id = decode_reset_token(body.token)
    except JWTError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "RESET_INVALID",
                    "message": "Reset link is invalid or expired — request a new one."},
        ) from exc
    user = await _load_user(session, user_id=user_id)
    if user is None or not user["is_active"]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "RESET_INVALID",
                    "message": "Reset link is invalid or expired — request a new one."},
        )
    await session.execute(
        text("UPDATE public.users SET password_hash = :p WHERE id = :id"),
        {"p": hash_password(body.password), "id": user_id},
    )
    await session.execute(
        text("UPDATE public.refresh_tokens SET revoked = true, revoked_at = NOW() "
             "WHERE user_id = :id AND revoked = false"),
        {"id": user_id},
    )
    await session.commit()
    return SuccessResponse(data=ForgotAck(), meta=build_meta())


@router.get("/me", response_model=SuccessResponse[AuthUser])
async def me(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessResponse[AuthUser]:
    user = await _load_user(session, user_id=current.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=_UNAUTH)
    return SuccessResponse(
        data=AuthUser(
            id=user["id"], email=user["email"], role=user["role"],
            org_id=user["org_id"], full_name=user["full_name"],
            permitted_tenants=current.permitted_tenants,
            tenant_id=await _org_tenant_slug(session, user["org_id"]),
        ),
        meta=build_meta(),
    )
