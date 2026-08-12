"""Validation tests for the segment criteria DSL (spec §3)."""

import pytest
from pydantic import ValidationError

from app.modules.segments.criteria import ALL_METRICS, WINDOWED_METRICS, SegmentCriteria


def parse_criteria(payload: dict[str, object]) -> SegmentCriteria:
    """Parse and validate a criteria payload.

    Args:
        payload: Raw dict shaped like a `SegmentCriteria` document.

    Returns:
        The validated `SegmentCriteria` instance.
    """
    return SegmentCriteria.model_validate(payload)


def test_minimal_and_criteria_validates() -> None:
    """Verify a single-condition AND document validates and round-trips fields."""
    criteria = parse_criteria(
        {
            "v": 1,
            "op": "AND",
            "conditions": [
                {"metric": "txn_sum", "txn_type": "p2p", "window_days": 90, "gte": 5000}
            ],
        }
    )
    assert criteria.conditions[0].metric == "txn_sum"


def test_or_with_multiple_comparators() -> None:
    """Verify an OR document with two conditions, one using both gte and lte, validates."""
    criteria = parse_criteria(
        {
            "v": 1,
            "op": "OR",
            "conditions": [
                {"metric": "days_since_last_txn", "lte": 14},
                {"metric": "account_age_days", "gte": 1, "lte": 30},
            ],
        }
    )
    assert criteria.op == "OR"


def test_unknown_metric_rejected() -> None:
    """Verify a metric name outside the registry is rejected."""
    with pytest.raises(ValidationError):
        parse_criteria({"v": 1, "op": "AND", "conditions": [{"metric": "shoe_size", "gte": 1}]})


def test_condition_without_comparator_rejected() -> None:
    """Verify a condition with no gte/lte/eq comparator is rejected."""
    with pytest.raises(ValidationError, match="at least one of gte/lte/eq"):
        parse_criteria({"v": 1, "op": "AND", "conditions": [{"metric": "txn_count"}]})


def test_filters_rejected_on_non_transactional_metric() -> None:
    """Verify txn_type and window_days are rejected on metrics that don't support them."""
    with pytest.raises(ValidationError, match="txn_type not allowed on metric 'account_age_days'"):
        parse_criteria(
            {
                "v": 1,
                "op": "AND",
                "conditions": [{"metric": "account_age_days", "txn_type": "p2p", "gte": 1}],
            }
        )
    with pytest.raises(ValidationError, match="window_days not allowed on metric 'wallet_balance'"):
        parse_criteria(
            {
                "v": 1,
                "op": "AND",
                "conditions": [{"metric": "wallet_balance", "window_days": 7, "gte": 1}],
            }
        )


def test_empty_conditions_rejected() -> None:
    """Verify an empty conditions list is rejected."""
    with pytest.raises(ValidationError):
        parse_criteria({"v": 1, "op": "AND", "conditions": []})


def test_nested_condition_object_rejected() -> None:
    """Verify a nested op object in place of a flat condition is rejected."""
    with pytest.raises(ValidationError):
        parse_criteria(
            {
                "v": 1,
                "op": "AND",
                "conditions": [{"op": "OR", "conditions": [{"metric": "txn_count", "gte": 1}]}],
            }
        )


def test_unsupported_version_rejected() -> None:
    """Verify a document version other than 1 is rejected."""
    with pytest.raises(ValidationError):
        parse_criteria({"v": 2, "op": "AND", "conditions": [{"metric": "txn_count", "gte": 1}]})


def test_window_days_bounds() -> None:
    """Verify window_days outside the 1-365 range is rejected."""
    with pytest.raises(ValidationError):
        parse_criteria(
            {
                "v": 1,
                "op": "AND",
                "conditions": [{"metric": "txn_count", "window_days": 0, "gte": 1}],
            }
        )
    with pytest.raises(ValidationError):
        parse_criteria(
            {
                "v": 1,
                "op": "AND",
                "conditions": [{"metric": "txn_count", "window_days": 366, "gte": 1}],
            }
        )


def test_more_than_ten_conditions_rejected() -> None:
    """Verify a document with more than 10 conditions is rejected."""
    conditions = [{"metric": "txn_count", "gte": 1} for _ in range(11)]
    with pytest.raises(ValidationError):
        parse_criteria({"v": 1, "op": "AND", "conditions": conditions})


def test_eq_alone_accepted() -> None:
    """Verify a condition using only eq (no gte/lte) validates."""
    criteria = parse_criteria(
        {"v": 1, "op": "AND", "conditions": [{"metric": "referral_count", "eq": 3}]}
    )
    assert criteria.conditions[0].eq == 3


def test_eq_combined_with_gte_rejected() -> None:
    """Verify eq combined with gte is rejected as an ambiguous condition."""
    with pytest.raises(ValidationError, match="cannot be combined"):
        parse_criteria(
            {"v": 1, "op": "AND", "conditions": [{"metric": "referral_count", "eq": 3, "gte": 1}]}
        )


def test_gte_greater_than_lte_rejected() -> None:
    """Verify gte > lte is rejected since the condition could never match."""
    with pytest.raises(ValidationError, match="can never match"):
        parse_criteria(
            {
                "v": 1,
                "op": "AND",
                "conditions": [{"metric": "account_age_days", "gte": 30, "lte": 10}],
            }
        )


def test_negative_threshold_rejected() -> None:
    """Verify a negative comparator value is rejected since all v1 metrics are non-negative."""
    with pytest.raises(ValidationError):
        parse_criteria(
            {"v": 1, "op": "AND", "conditions": [{"metric": "wallet_balance", "gte": -1}]}
        )


def test_windowed_metrics_are_subset_of_all_metrics() -> None:
    """Verify WINDOWED_METRICS stays a subset of the single-source ALL_METRICS vocabulary."""
    assert WINDOWED_METRICS <= ALL_METRICS


def test_json_round_trip_preserves_criteria() -> None:
    """Verify a criteria document survives a JSON-mode dump and re-parse unchanged."""
    criteria = parse_criteria(
        {
            "v": 1,
            "op": "AND",
            "conditions": [
                {"metric": "txn_sum", "txn_type": "p2p", "window_days": 90, "gte": 5000}
            ],
        }
    )
    round_tripped = SegmentCriteria.model_validate(criteria.model_dump(mode="json"))
    assert round_tripped == criteria
