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


class AuthUser(BaseModel):
    id: UUID
    email: str
    role: str
    org_id: UUID
    full_name: str | None = None
    permitted_tenants: list[str] = []


class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AuthUser


class AccessData(BaseModel):
    access_token: str
    token_type: str = "bearer"
