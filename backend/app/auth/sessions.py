"""Redis-backed opaque session + registration tokens.

Two token shapes use the same store, different prefixes:

  `session:<token>`      — user session; TTL = settings.SESSION_TTL_SECONDS
                           sliding (refreshed on every authenticated read)
  `regtoken:<token>`     — short-lived proof of phone-ownership after OTP
                           verify, used as the auth for /pin/set; TTL =
                           settings.REGTOKEN_TTL_SECONDS, single-use

Both TTLs live in `app.config.Settings` so they can be tuned per
environment (NFR-0180: mobile ≤ 15 min, USSD ≤ 5 min in production;
local dev wants headroom for setup + load testing). The value is a JSON
dict — small, opaque to the client. Never logged. Per NFR-0170: tokens
NEVER appear in DB rows, audit log, or application logs.
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from app.auth.hashing import generate_token
from app.config import settings
from app.redis_client import redis_client

SESSION_PREFIX = "session:"
REGTOKEN_PREFIX = "regtoken:"
# Per-user reverse index: a Redis SET of the user's live session tokens. Lets an
# admin access-lock revoke EVERY session for a user in one shot
# (`invalidate_user_sessions`) — without it, sessions have no per-user handle.
USER_SESSIONS_PREFIX = "user_sessions:"


async def create_session(user_id: UUID, tenant_id: UUID, channel: str = "mobile") -> str:
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
        ex=settings.SESSION_TTL_SECONDS,
    )
    # Add the token to the per-user index so an access-lock can revoke it. The
    # set's TTL is refreshed to SESSION_TTL on every new session so a purely
    # idle-then-abandoned index eventually expires; individual tokens still
    # carry their own sliding TTL.
    user_set_key = USER_SESSIONS_PREFIX + str(user_id)
    await redis_client.sadd(user_set_key, token)
    await redis_client.expire(user_set_key, settings.SESSION_TTL_SECONDS)
    return token


async def read_session(token: str, *, refresh_ttl: bool = True) -> dict[str, Any] | None:
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
    payload = cast("dict[str, Any]", json.loads(raw))
    if refresh_ttl:
        await redis_client.expire(SESSION_PREFIX + token, settings.SESSION_TTL_SECONDS)
        # Slide the per-user index set in lockstep with the session key. Without
        # this a long-lived (sliding) session outlives its index entry, so an
        # access-lock's invalidate_user_sessions would find an empty set and fail
        # to kill exactly the active sessions it most needs to (code-review BLOCKER).
        await redis_client.expire(
            USER_SESSIONS_PREFIX + payload["user_id"], settings.SESSION_TTL_SECONDS
        )
    return payload


async def invalidate_session(token: str) -> None:
    """Delete a session — used by /auth/logout. Safe if token is unknown.

    Also removes the token from its owner's per-user index so the reverse index
    stays consistent (no dangling tokens for `invalidate_user_sessions` to chase).
    We read the payload first to learn the user_id; an unknown token is a no-op.
    """
    raw = await redis_client.get(SESSION_PREFIX + token)
    await redis_client.delete(SESSION_PREFIX + token)
    if raw is not None:
        payload = json.loads(raw)
        user_id = payload.get("user_id")
        if user_id:
            await redis_client.srem(USER_SESSIONS_PREFIX + user_id, token)


async def invalidate_user_sessions(user_id: UUID) -> int:
    """Revoke EVERY live session for a user — the admin login-lock hammer.

    Reads the per-user index, deletes each `session:<token>` key, then deletes
    the index set itself. Idempotent and safe when the user has no sessions.

    Args:
        user_id: The user whose sessions are being killed.

    Returns:
        The number of session tokens that were in the index (best-effort count
        of sessions revoked). Zero when the user had no live sessions.
    """
    user_set_key = USER_SESSIONS_PREFIX + str(user_id)
    # decode_responses=True on the client → members are str (see redis_client.py).
    tokens = cast("set[str]", await redis_client.smembers(user_set_key))
    if tokens:
        await redis_client.delete(*(SESSION_PREFIX + t for t in tokens))
    await redis_client.delete(user_set_key)
    return len(tokens)


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
        ex=settings.REGTOKEN_TTL_SECONDS,
    )
    return token


async def read_registration_token(token: str) -> dict[str, Any] | None:
    """Return the payload or None. Does NOT refresh TTL — this is single-use."""
    raw = await redis_client.get(REGTOKEN_PREFIX + token)
    return json.loads(raw) if raw else None


async def consume_registration_token(token: str) -> dict[str, Any] | None:
    """Read-and-delete: atomic single-use semantics.

    Returns the payload if the token was valid; None otherwise. After this
    call, the token is gone whether or not the caller succeeds in using it.
    """
    raw = await redis_client.getdel(REGTOKEN_PREFIX + token)
    return json.loads(raw) if raw else None
