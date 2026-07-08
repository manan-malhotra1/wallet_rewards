"""Async Redis client — process-singleton for sessions, lockouts, rate limits.

Wraps `redis.asyncio` so the rest of the app doesn't depend on the library
directly. Test fixtures can override `redis_client` to a fake.
"""

from __future__ import annotations

import redis.asyncio as redis

from app.config import settings

# Single connection pool shared across the app. asyncpg-style: cheap to
# acquire from, expensive to keep open per request.
redis_client: redis.Redis = redis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
)
