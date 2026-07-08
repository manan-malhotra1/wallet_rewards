"""OTP send rate-limiting — Redis-backed, prevents SMS-credit drain.

Two windows enforced separately:
  - 1 OTP per 60 seconds per phone (short burst)
  - 5 OTPs per hour per phone (long-tail)

If either window is exceeded, `/otp/send` returns 429.
"""

from __future__ import annotations

from app.redis_client import redis_client

SHORT_KEY = "otp_short:{phone}"  # 60-second window
LONG_KEY = "otp_long:{phone}"  # 1-hour rolling counter

SHORT_WINDOW_SECONDS = 60
LONG_WINDOW_SECONDS = 60 * 60
LONG_WINDOW_MAX = 5


async def consume_otp_send_quota(phone: str) -> tuple[bool, int]:
    """Try to consume one OTP-send token for this phone.

    Returns:
        (allowed, retry_after_seconds) — `allowed=True` if the send may
        proceed; `retry_after_seconds` is the time until the smaller of the
        two limits releases.
    """
    short_key = SHORT_KEY.format(phone=phone)
    long_key = LONG_KEY.format(phone=phone)

    # Short window: 1 OTP per 60s.
    short_exists = await redis_client.exists(short_key)
    if short_exists:
        ttl = await redis_client.ttl(short_key)
        return False, max(ttl, 1)

    # Long window: 5 OTPs per hour.
    long_count = await redis_client.get(long_key)
    if long_count is not None and int(long_count) >= LONG_WINDOW_MAX:
        ttl = await redis_client.ttl(long_key)
        return False, max(ttl, 1)

    # Allowed — record the send.
    await redis_client.set(short_key, "1", ex=SHORT_WINDOW_SECONDS)
    new_long_count = await redis_client.incr(long_key)
    if new_long_count == 1:
        await redis_client.expire(long_key, LONG_WINDOW_SECONDS)
    return True, 0


# --- External-API per-key rate limit (Epic 14) -----------------------------
# Fixed-window counter per API key. Read at call time (module globals, not
# default args) so tests — and a future settings-backed override — can adjust
# the ceiling without rebinding the function.
API_KEY_RATE_LIMIT = 60  # requests per window
API_KEY_RATE_WINDOW_SECONDS = 60  # window length (1 minute)
API_KEY_RL_KEY = "apikey_rl:{key_id}"


async def consume_api_key_quota(key_id: str) -> tuple[bool, int]:
    """Consume one request token for `key_id` in the current fixed window.

    Returns:
        (allowed, retry_after_seconds). `allowed=False` once the window count
        exceeds API_KEY_RATE_LIMIT; `retry_after_seconds` is the time until the
        window resets.
    """
    rl_key = API_KEY_RL_KEY.format(key_id=key_id)
    count = await redis_client.incr(rl_key)
    if count == 1:
        await redis_client.expire(rl_key, API_KEY_RATE_WINDOW_SECONDS)
    if count > API_KEY_RATE_LIMIT:
        ttl = await redis_client.ttl(rl_key)
        return False, max(ttl, 1)
    return True, 0
