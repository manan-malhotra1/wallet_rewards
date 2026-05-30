"""Redis-backed opaque session + registration tokens.

Two token shapes use the same store, different prefixes:

  `session:<token>`      — user session, TTL = SESSION_TTL_SECONDS (15min)
  `regtoken:<token>`     — short-lived proof of phone-ownership after OTP verify
                           used as the auth for /pin/set; TTL = 10min

The value is a JSON dict — small, opaque to the client. Never logged. Per
NFR-0170: tokens NEVER appear in DB rows, audit log, or application logs.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.auth.hashing import generate_token
from app.redis_client import redis_client

SESSION_PREFIX = "session:"
REGTOKEN_PREFIX = "regtoken:"

# 15 minutes inactivity per NFR-0180 (mobile app). USSD will be 5 min in a
# later phase when the USSD channel ships.
SESSION_TTL_SECONDS = 15 * 60
REGTOKEN_TTL_SECONDS = 10 * 60


async def create_session(
    user_id: UUID, tenant_id: UUID, channel: str = "mobile"
) -> str:
    """Issue a fresh session_token for a successful PIN-auth.

    Args:
        user_id: Authenticated user.
        tenant_id: Tenant of the user (resolved at PIN-auth time).
        channel: 'mobile' or 'ussd'. Phase F.2 only emits 'mobile'.

    Returns:
        The opaque token string to return to the caller. The token itself is
        the lookup key — store nothing else client-side.
    """
    token = generate_token()
    payload = {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "channel": channel,
    }
    await redis_client.set(
        SESSION_PREFIX + token,
        json.dumps(payload),
        ex=SESSION_TTL_SECONDS,
    )
    return token


async def read_session(token: str, *, refresh_ttl: bool = True) -> dict | None:
    """Look up a session by token. Sliding TTL by default.

    Args:
        token: The Bearer token from Authorization header.
        refresh_ttl: When True, refresh the TTL on read (sliding expiry).
            This is the right behaviour for "active user" sessions.

    Returns:
        The payload dict, or None if the token is unknown / expired.
    """
    raw = await redis_client.get(SESSION_PREFIX + token)
    if raw is None:
        return None
    if refresh_ttl:
        await redis_client.expire(SESSION_PREFIX + token, SESSION_TTL_SECONDS)
    return json.loads(raw)


async def invalidate_session(token: str) -> None:
    """Delete a session — used by /auth/logout. Safe if token is unknown."""
    await redis_client.delete(SESSION_PREFIX + token)


# -----------------------------------------------------------------------------
# Registration tokens (between OTP verify and PIN set)
# -----------------------------------------------------------------------------


async def create_registration_token(user_id: UUID, phone: str) -> str:
    """Issue a short-lived token proving the holder verified an OTP for `phone`.

    The /pin/set endpoint trades this token for permission to set the user's
    PIN. It's a deliberate two-step flow so the PIN payload is never sent in
    the OTP exchange.
    """
    token = generate_token()
    payload: dict[str, Any] = {"user_id": str(user_id), "phone": phone}
    await redis_client.set(
        REGTOKEN_PREFIX + token,
        json.dumps(payload),
        ex=REGTOKEN_TTL_SECONDS,
    )
    return token


async def read_registration_token(token: str) -> dict | None:
    """Return the payload or None. Does NOT refresh TTL — this is single-use."""
    raw = await redis_client.get(REGTOKEN_PREFIX + token)
    return json.loads(raw) if raw else None


async def consume_registration_token(token: str) -> dict | None:
    """Read-and-delete: atomic single-use semantics.

    Returns the payload if the token was valid; None otherwise. After this
    call, the token is gone whether or not the caller succeeds in using it.
    """
    raw = await redis_client.getdel(REGTOKEN_PREFIX + token)
    return json.loads(raw) if raw else None
