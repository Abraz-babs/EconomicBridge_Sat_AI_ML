"""Auth primitives: password hashing + JWT issue/verify + invite tokens.

Re-introduces the auth layer that the open-access pivot removed, but scoped to
the control plane: super-admin (platform operator) and tenant accounts. The
public dashboard stays anonymous — only `/admin/*` and account actions require
a token.

Tokens (CLAUDE.md §4.1):
  * access  — short-lived (15 min) JWT carrying identity + role + tenant scope.
  * refresh — opaque random string; only its SHA-256 hash is stored
              (public.refresh_tokens), so sessions are individually revocable
              and the raw token never lands in the DB.
  * invite  — short-lived (48h) signed JWT used once to activate an account and
              set the first password. Single-use is enforced at the router by
              requiring the user to still be inactive.

bcrypt is used directly (not via passlib) to avoid the passlib↔bcrypt-5
version-introspection warning.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from config import get_settings

# Token "type" claim — guards against using e.g. an invite token as an access
# token (same secret, different purpose).
ACCESS_TOKEN_TYPE = "access"
INVITE_TOKEN_TYPE = "invite"

# bcrypt silently truncates input beyond 72 bytes; reject longer passwords up
# front so two distinct long passwords can't collide on the truncation.
_BCRYPT_MAX_BYTES = 72


# ─── Passwords ──────────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Return a bcrypt hash (utf-8 str) of `plain`."""
    pw = plain.encode("utf-8")
    if len(pw) > _BCRYPT_MAX_BYTES:
        raise ValueError("password too long (max 72 bytes)")
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time check of `plain` against a stored bcrypt hash."""
    if not hashed:
        return False
    pw = plain.encode("utf-8")
    if len(pw) > _BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except ValueError:
        # Malformed/empty stored hash — treat as no-match, never raise.
        return False


# ─── Access (JWT) ─────────────────────────────────────────────────────────


def create_access_token(
    *,
    user_id: UUID,
    role: str,
    org_id: UUID,
    permitted_tenants: list[str],
) -> str:
    """Mint a signed access token. `sub` is the user id; scope claims let the
    API authorise without a DB round-trip on every request."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "typ": ACCESS_TOKEN_TYPE,
        "role": role,
        "org": str(org_id),
        "tenants": permitted_tenants,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.jwt_access_ttl_min)).timestamp()),
    }
    return jwt.encode(claims, s.jwt_secret_key, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode + verify an access token. Raises JWTError on bad sig/expiry/type."""
    s = get_settings()
    claims = jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])
    if claims.get("typ") != ACCESS_TOKEN_TYPE:
        raise JWTError("not an access token")
    return claims


# ─── Refresh (opaque + hashed) ──────────────────────────────────────────────


def new_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex). Store the hash; hand the raw to the
    client once."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    """SHA-256 hex of a token — used for refresh-token lookup/revocation."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ─── Invite (single-use activation JWT) ─────────────────────────────────────


def create_invite_token(user_id: UUID) -> str:
    """Mint a short-lived activation token for a freshly-provisioned account."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "typ": INVITE_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=s.invite_ttl_hours)).timestamp()),
    }
    return jwt.encode(claims, s.jwt_secret_key, algorithm=s.jwt_algorithm)


def decode_invite_token(token: str) -> UUID:
    """Return the user id from a valid invite token. Raises JWTError otherwise."""
    s = get_settings()
    claims = jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])
    if claims.get("typ") != INVITE_TOKEN_TYPE:
        raise JWTError("not an invite token")
    return UUID(claims["sub"])
