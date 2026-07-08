"""Per-key fixed-window rate limiting for the external API (Epic 14 S5)."""

from __future__ import annotations

import pytest

import app.auth.rate_limit as rl
from app.auth.rate_limit import consume_api_key_quota


@pytest.mark.asyncio
async def test_requests_within_limit_allowed_then_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Up to the limit is allowed; the next request is blocked with a retry hint."""
    monkeypatch.setattr(rl, "API_KEY_RATE_LIMIT", 2)
    a1, _ = await consume_api_key_quota("sak_rl_a")
    a2, _ = await consume_api_key_quota("sak_rl_a")
    a3, retry = await consume_api_key_quota("sak_rl_a")
    assert a1 is True
    assert a2 is True
    assert a3 is False
    assert retry >= 1


@pytest.mark.asyncio
async def test_buckets_are_per_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """One key exhausting its quota does not affect another key."""
    monkeypatch.setattr(rl, "API_KEY_RATE_LIMIT", 1)
    assert (await consume_api_key_quota("key-A"))[0] is True
    assert (await consume_api_key_quota("key-B"))[0] is True
    assert (await consume_api_key_quota("key-A"))[0] is False
