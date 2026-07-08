"""Failed-attempt counter + lockout — Redis-backed, TTL-driven.

Per NFR-0190: after `PIN_MAX_ATTEMPTS` consecutive failed PIN/OTP attempts,
lock the account for `PIN_LOCKOUT_MINUTES`.

Per NFR-0270: unusual fraud signal (reward velocity) is a separate signal —
NOT handled here.

Counter and lockout are tracked SEPARATELY:
  `pin_fails:<user_id>`   counter — increment on fail; reset on success or lock
  `lockout:<user_id>`     present iff account is currently locked; TTL = lockout window
"""

from __future__ import annotations

from uuid import UUID

from app.config import settings
from app.redis_client import redis_client

FAILS_KEY = "pin_fails:{user_id}"
LOCKOUT_KEY = "lockout:{user_id}"

# Counter TTL — fail history doesn't haunt the user forever. One hour rolling
# window: after 60 min of no failed attempts, the counter resets.
FAILS_TTL_SECONDS = 60 * 60


async def is_locked(user_id: UUID) -> bool:
    """True if the user is currently locked out."""
    return bool(await redis_client.exists(LOCKOUT_KEY.format(user_id=user_id)))


async def lockout_seconds_remaining(user_id: UUID) -> int:
    """How many seconds until the lockout lifts. 0 if not locked."""
    ttl = await redis_client.ttl(LOCKOUT_KEY.format(user_id=user_id))
    # Redis returns -1 if no TTL set, -2 if key doesn't exist.
    return max(ttl, 0)


async def register_failure(user_id: UUID) -> int:
    """Bump the failed-attempt counter; lock the user if threshold reached.

    Returns:
        The new failure count after increment. When ≥ PIN_MAX_ATTEMPTS, the
        caller can choose to surface a different error code, but the lockout
        key is already set.
    """
    key = FAILS_KEY.format(user_id=user_id)
    count = await redis_client.incr(key)
    # First increment: set the rolling window TTL.
    if count == 1:
        await redis_client.expire(key, FAILS_TTL_SECONDS)

    if count >= settings.PIN_MAX_ATTEMPTS:
        await redis_client.set(
            LOCKOUT_KEY.format(user_id=user_id),
            "1",
            ex=settings.PIN_LOCKOUT_MINUTES * 60,
        )
        # Reset the counter — the next attempt after lockout expires starts fresh.
        await redis_client.delete(key)

    return int(count)


async def reset_failures(user_id: UUID) -> None:
    """Clear the failed-attempt counter after a successful auth."""
    await redis_client.delete(FAILS_KEY.format(user_id=user_id))
