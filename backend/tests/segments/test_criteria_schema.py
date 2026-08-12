"""Validation tests for the segment criteria DSL (spec §3)."""

import pytest
from pydantic import ValidationError

from app.modules.segments.criteria import SegmentCriteria


def valid(payload: dict) -> SegmentCriteria:
    """Parse and validate a criteria payload.

    Args:
        payload: Raw dict shaped like a `SegmentCriteria` document.

    Returns:
        The validated `SegmentCriteria` instance.
    """
    return SegmentCriteria.model_validate(payload)


def test_minimal_and_criteria_validates() -> None:
    """Verify a single-condition AND document validates and round-trips fields."""
    c = valid(
        {
            "v": 1,
            "op": "AND",
            "conditions": [
                {"metric": "txn_sum", "txn_type": "p2p", "window_days": 90, "gte": 5000}
            ],
        }
    )
    assert c.conditions[0].metric == "txn_sum"


def test_or_with_multiple_comparators() -> None:
    """Verify an OR document with two conditions, one using both gte and lte, validates."""
    c = valid(
        {
            "v": 1,
            "op": "OR",
            "conditions": [
                {"metric": "days_since_last_txn", "lte": 14},
                {"metric": "account_age_days", "gte": 1, "lte": 30},
            ],
        }
    )
    assert c.op == "OR"


def test_unknown_metric_rejected() -> None:
    """Verify a metric name outside the registry is rejected."""
    with pytest.raises(ValidationError):
        valid({"v": 1, "op": "AND", "conditions": [{"metric": "shoe_size", "gte": 1}]})


def test_condition_without_comparator_rejected() -> None:
    """Verify a condition with no gte/lte/eq comparator is rejected."""
    with pytest.raises(ValidationError):
        valid({"v": 1, "op": "AND", "conditions": [{"metric": "txn_count"}]})


def test_filters_rejected_on_non_transactional_metric() -> None:
    """Verify txn_type and window_days are rejected on metrics that don't support them."""
    with pytest.raises(ValidationError):
        valid(
            {
                "v": 1,
                "op": "AND",
                "conditions": [{"metric": "account_age_days", "txn_type": "p2p", "gte": 1}],
            }
        )
    with pytest.raises(ValidationError):
        valid(
            {
                "v": 1,
                "op": "AND",
                "conditions": [{"metric": "wallet_balance", "window_days": 7, "gte": 1}],
            }
        )


def test_empty_conditions_and_nesting_and_bad_version_rejected() -> None:
    """Verify empty condition lists, nested op objects, and unsupported versions are rejected."""
    with pytest.raises(ValidationError):
        valid({"v": 1, "op": "AND", "conditions": []})
    with pytest.raises(ValidationError):
        valid({"v": 2, "op": "AND", "conditions": [{"metric": "txn_count", "gte": 1}]})
    with pytest.raises(ValidationError):  # nested op object is not a condition
        valid(
            {
                "v": 1,
                "op": "AND",
                "conditions": [{"op": "OR", "conditions": [{"metric": "txn_count", "gte": 1}]}],
            }
        )


def test_window_days_bounds() -> None:
    """Verify window_days outside the 1-365 range is rejected."""
    with pytest.raises(ValidationError):
        valid(
            {
                "v": 1,
                "op": "AND",
                "conditions": [{"metric": "txn_count", "window_days": 0, "gte": 1}],
            }
        )
    with pytest.raises(ValidationError):
        valid(
            {
                "v": 1,
                "op": "AND",
                "conditions": [{"metric": "txn_count", "window_days": 366, "gte": 1}],
            }
        )
