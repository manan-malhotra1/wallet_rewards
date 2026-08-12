"""Segment criteria DSL (v1) — the single contract for dynamic segments.

Shared by: manual builder validation, seed data, the evaluator, and (Phase 2)
the AI draft compiler. Spec: docs/superpowers/specs/2026-08-12-ai-segmentation-design.md §3.

DESIGN DECISION: bounds are closed intervals (gte/lte/eq). Strict bounds are
intentionally unsupported in v1; express "more than N" as gte with the
smallest meaningful increment for the metric.
"""

from __future__ import annotations

from typing import Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Metric names must stay in sync with app.modules.segments.metrics.METRIC_BUILDERS.
# Enforced by tests/segments/test_metrics.py::test_registry_matches_dsl_vocabulary
# (a runtime assert here would be stripped under python -O, so the registry
# test is the source of truth for keeping the two vocabularies in sync).
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

# ALL_METRICS is derived from MetricName so the vocabulary has exactly one
# source of truth — never list metric names a second time.
ALL_METRICS: frozenset[str] = frozenset(get_args(MetricName))
TRANSACTIONAL_METRICS: frozenset[str] = frozenset({"txn_count", "txn_sum"})
WINDOWED_METRICS: frozenset[str] = TRANSACTIONAL_METRICS | {"points_redeemed", "rewards_earned"}


class Condition(BaseModel):
    """One metric threshold. At least one comparator must be present.

    `window_days`, when set, is a rolling UTC-instant window: the evaluator
    filters rows where `created_at >= now(UTC) - window_days days`, inclusive
    of the boundary instant.
    """

    model_config = ConfigDict(extra="forbid")

    metric: MetricName
    txn_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="Transaction-type filter; only valid on txn_count/txn_sum",
    )
    window_days: int | None = Field(
        default=None,
        ge=1,
        le=365,
        description=(
            "Rolling window: created_at >= now (UTC) - N days, inclusive; only "
            "valid on windowed metrics; capped at 365 to bound query cost"
        ),
    )
    # Comparators are deliberately plain JSON numbers (not Decimal) so the
    # criteria document stays JSON-native for JSONB storage and the Phase-2
    # JSON Schema. The evaluator MUST compare via `Decimal(str(cond.gte))` —
    # never convert float to Decimal directly (`Decimal(0.1) != Decimal("0.1")`,
    # and `Decimal("0.1") >= 0.1` is False due to binary float representation).
    # Precision is bounded to ~15 significant digits by the float round-trip.
    gte: float | None = Field(default=None, ge=0, description="Inclusive lower bound")
    lte: float | None = Field(default=None, ge=0, description="Inclusive upper bound")
    eq: float | None = Field(
        default=None, ge=0, description="Exact match; cannot combine with gte/lte"
    )

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        """Reject comparator-less conditions and filters on unsupported metrics.

        Returns:
            The validated `Condition` instance, unchanged.

        Raises:
            ValueError: No comparator is present, `eq` is combined with
                `gte`/`lte`, `gte` exceeds `lte`, or `txn_type`/`window_days`
                is set on a metric that does not support it.
        """
        if self.gte is None and self.lte is None and self.eq is None:
            raise ValueError("condition needs at least one of gte/lte/eq")
        if self.eq is not None and (self.gte is not None or self.lte is not None):
            raise ValueError("eq cannot be combined with gte/lte")
        if self.gte is not None and self.lte is not None and self.gte > self.lte:
            raise ValueError(
                f"gte ({self.gte}) must be <= lte ({self.lte}) — condition can never match"
            )
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
