"""Unit tests for the analytics window/granularity helpers (pure functions)."""

from datetime import UTC, datetime

import pytest

from app.modules.analytics.service import resolve_window, validate_granularity


def test_resolve_window_7d_gives_two_aligned_windows():
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    current, previous = resolve_window("7d", now=now)
    # current window is the last 7 days ending now
    assert (current.end - current.start).days == 7
    # previous window is the 7 days immediately before current
    assert previous.end == current.start
    assert (previous.end - previous.start).days == 7


def test_resolve_window_rejects_unknown_range():
    with pytest.raises(ValueError):
        resolve_window("all-time", now=datetime(2026, 7, 31, tzinfo=UTC))


def test_validate_granularity_rejects_unknown():
    with pytest.raises(ValueError):
        validate_granularity("hourly")
