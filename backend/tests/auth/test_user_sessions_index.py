"""Tracking and revoking user sessions.

`create_session` maintains a Redis SET `user_sessions:<user_id>` so an admin
login-lock can revoke every session for a user at once. Covers: the index is
populated on create, `invalidate_session` keeps it consistent, and
`invalidate_user_sessions` kills every live session and returns the count.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app import redis_client as redis_module
from app.auth.sessions import (
    SESSION_PREFIX,
    USER_SESSIONS_PREFIX,
    create_session,
    invalidate_session,
    invalidate_user_sessions,
    read_session,
)


def _redis():
    """Return the per-test Redis client (patched by the autouse conftest fixture).

    Reading the attribute at call time (not import time) picks up the fresh
    per-test client the conftest binds, avoiding the closed-event-loop singleton.
    """
    return redis_module.redis_client


@pytest.mark.asyncio
async def test_create_session_adds_token_to_user_index() -> None:
    """Verify a new sign-in session is tracked for the user"""
    user_id, tenant_id = uuid4(), uuid4()
    token = await create_session(user_id, tenant_id)

    members = await _redis().smembers(USER_SESSIONS_PREFIX + str(user_id))
    assert token in members
    # The session key itself exists.
    assert await _redis().get(SESSION_PREFIX + token) is not None


@pytest.mark.asyncio
async def test_invalidate_session_removes_token_from_index() -> None:
    """Verify signing out clears the user's session"""
    user_id, tenant_id = uuid4(), uuid4()
    token = await create_session(user_id, tenant_id)

    await invalidate_session(token)

    members = await _redis().smembers(USER_SESSIONS_PREFIX + str(user_id))
    assert token not in members
    assert await read_session(token) is None


@pytest.mark.asyncio
async def test_invalidate_user_sessions_kills_all_and_returns_count() -> None:
    """Verify an administrator can end all of a user's sessions at once"""
    user_id, tenant_id = uuid4(), uuid4()
    tokens = [await create_session(user_id, tenant_id) for _ in range(3)]

    killed = await invalidate_user_sessions(user_id)

    assert killed == 3
    for token in tokens:
        assert await read_session(token) is None
    # The index set itself is gone.
    assert await _redis().exists(USER_SESSIONS_PREFIX + str(user_id)) == 0


@pytest.mark.asyncio
async def test_invalidate_user_sessions_no_sessions_is_zero_noop() -> None:
    """Verify ending sessions for a user with none is harmless"""
    assert await invalidate_user_sessions(uuid4()) == 0


@pytest.mark.asyncio
async def test_read_session_slides_the_user_index_ttl() -> None:
    """Verify an active session stays revocable as it is used

    Regression (code-review BLOCKER): the index set must never expire out from
    under a still-live session, or a later login-lock would find an empty set
    and fail to kill an active session. Simulate the set nearing expiry, then a
    read must bump it back so the session is still revocable.
    """
    user_id, tenant_id = uuid4(), uuid4()
    token = await create_session(user_id, tenant_id)
    set_key = USER_SESSIONS_PREFIX + str(user_id)

    # Simulate the index set having slid close to expiry while the token lives.
    await _redis().expire(set_key, 3)
    assert await _redis().ttl(set_key) <= 3

    # A sliding read must push the set TTL back up in lockstep with the token.
    assert await read_session(token) is not None
    assert await _redis().ttl(set_key) > 3

    # And the session is still revocable afterwards.
    assert await invalidate_user_sessions(user_id) == 1
    assert await read_session(token) is None


@pytest.mark.asyncio
async def test_invalidate_user_sessions_leaves_other_users_untouched() -> None:
    """Verify ending one user's sessions leaves other users signed in"""
    victim, bystander, tenant_id = uuid4(), uuid4(), uuid4()
    victim_token = await create_session(victim, tenant_id)
    bystander_token = await create_session(bystander, tenant_id)

    await invalidate_user_sessions(victim)

    assert await read_session(victim_token) is None
    assert await read_session(bystander_token) is not None
