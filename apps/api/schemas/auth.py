"""Pydantic models for the auth endpoints."""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class ActivateRequest(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=72)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=72)


class ForgotAck(BaseModel):
    """Always the same body whether or not the email exists — the endpoint
    must never confirm which addresses have accounts (user enumeration)."""
    received: bool = True


class AuthUser(BaseModel):
    id: UUID
    email: str
    role: str
    org_id: UUID
    full_name: str | None = None
    permitted_tenants: list[str] = []
    # The registry slug of the user's OWN organisation (organisations.org_id
    # equals the tenant_registry id by onboarding construction). This — not
    # whichever tenant is being VIEWED — is what the user's subscription
    # (module locks) must key off. None for legacy/seed accounts.
    tenant_id: str | None = None


class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AuthUser


class AccessData(BaseModel):
    access_token: str
    token_type: str = "bearer"
