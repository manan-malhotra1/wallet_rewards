"""Segment criteria DSL (v1) — the single contract for dynamic segments.

Shared by: manual builder validation, seed data, the evaluator, and (Phase 2)
the AI draft compiler. Spec: docs/superpowers/specs/2026-08-12-ai-segmentation-design.md §3.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Metric names must stay in sync with app.modules.segments.metrics.METRIC_BUILDERS
# (the registry asserts this at import time — Task 3).
TRANSACTIONAL_METRICS = {"txn_count", "txn_sum"}
WINDOWED_METRICS = TRANSACTIONAL_METRICS | {"points_redeemed", "rewards_earned"}
ALL_METRICS = WINDOWED_METRICS | {
    "wallet_balance",
    "points_balance",
    "account_age_days",
    "days_since_last_txn",
    "referral_count",
}

MetricName = Literal[
    "txn_count",
    "txn_sum",
    "wallet_balance",
    "points_balance",
    "points_redeemed",
    "rewards_earned",
    "account_age_days",
    "days_since_last_txn",
    "referral_count",
]


class Condition(BaseModel):
    """One metric threshold. At least one comparator must be present."""

    model_config = ConfigDict(extra="forbid")

    metric: MetricName
    txn_type: str | None = Field(default=None, max_length=50)
    window_days: int | None = Field(default=None, ge=1, le=365)
    gte: float | None = None
    lte: float | None = None
    eq: float | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "Condition":
        """Reject comparator-less conditions and filters on unsupported metrics.

        Returns:
            The validated `Condition` instance, unchanged.

        Raises:
            ValueError: No comparator is present, or `txn_type`/`window_days` is
                set on a metric that does not support it.
        """
        if self.gte is None and self.lte is None and self.eq is None:
            raise ValueError("condition needs at least one of gte/lte/eq")
        if self.txn_type is not None and self.metric not in TRANSACTIONAL_METRICS:
            raise ValueError(f"txn_type not allowed on metric '{self.metric}'")
        if self.window_days is not None and self.metric not in WINDOWED_METRICS:
            raise ValueError(f"window_days not allowed on metric '{self.metric}'")
        return self


class SegmentCriteria(BaseModel):
    """Top-level criteria document: one AND/OR over 1-10 flat conditions."""

    model_config = ConfigDict(extra="forbid")

    v: Literal[1]
    op: Literal["AND", "OR"]
    conditions: list[Condition] = Field(min_length=1, max_length=10)
