"""Rate-limiting partner API calls."""

from __future__ import annotations

import pytest

import app.auth.rate_limit as rl
from app.auth.rate_limit import consume_api_key_quota


@pytest.mark.asyncio
async def test_requests_within_limit_allowed_then_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify an API key is rate-limited after too many calls"""
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
    """Verify one API key hitting its limit does not affect another"""
    monkeypatch.setattr(rl, "API_KEY_RATE_LIMIT", 1)
    assert (await consume_api_key_quota("key-A"))[0] is True
    assert (await consume_api_key_quota("key-B"))[0] is True
    assert (await consume_api_key_quota("key-A"))[0] is False
