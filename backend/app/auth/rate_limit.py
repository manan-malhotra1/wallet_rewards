"""OTP send rate-limiting — Redis-backed, prevents SMS-credit drain.

Two windows enforced separately:
  - 1 OTP per 60 seconds per phone (short burst)
  - 5 OTPs per hour per phone (long-tail)

If either window is exceeded, `/otp/send` returns 429.
"""
from __future__ import annotations

from app.redis_client import redis_client

SHORT_KEY = "otp_short:{phone}"   # 60-second window
LONG_KEY = "otp_long:{phone}"     # 1-hour rolling counter

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
