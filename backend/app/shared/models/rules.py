"""Rule, RuleCondition, UserRuleProgress, BonusMultiplier models — PRD §6.8.

Implements PRD Module 9. Phase C uses `first_time` and `milestone` rule types
only; the full 7-type schema is created up front so future rule types need
only evaluator additions, not schema migrations.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# Rule type constants — keep in sync with the CHECK constraint.
RULE_TYPE_MILESTONE = "milestone"
RULE_TYPE_STREAK = "streak"
RULE_TYPE_FIRST_TIME = "first_time"
RULE_TYPE_VALUE_BASED = "value_based"
RULE_TYPE_COMPOSITE = "composite"
RULE_TYPE_CAMPAIGN = "campaign"
RULE_TYPE_REFERRAL = "referral"

RULE_TYPES = (
    RULE_TYPE_MILESTONE,
    RULE_TYPE_STREAK,
    RULE_TYPE_FIRST_TIME,
    RULE_TYPE_VALUE_BASED,
    RULE_TYPE_COMPOSITE,
    RULE_TYPE_CAMPAIGN,
    RULE_TYPE_REFERRAL,
)

REWARD_TYPE_POINTS = "points"
REWARD_TYPE_CASHBACK = "cashback"

PROGRESS_STATUS_ACTIVE = "active"
PROGRESS_STATUS_COMPLETED = "completed"
PROGRESS_STATUS_DEACTIVATED = "deactivated"


class Rule(Base):
    """A configured reward condition (PRD §6.8).

    A rule fires when its conditions are met by a qualifying event. The
    rule_type determines which fields are meaningful:

      - first_time: fires once per user on the first matching event
      - milestone:  fires when `count_threshold` matching events have happened
                    (resets if `resets_after_trigger=True`)
      - streak, value_based, composite, campaign, referral: deferred to later phases
    """

    __tablename__ = "rules"
    __table_args__ = (
        CheckConstraint(
            "rule_type IN ("
            "'milestone', 'streak', 'first_time', 'value_based', "
            "'composite', 'campaign', 'referral'"
            ")",
            name="ck_rules_type",
        ),
        CheckConstraint(
            "reward_type IN ('points', 'cashback')",
            name="ck_rules_reward_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_rules_status",
        ),
        CheckConstraint(
            "time_window IS NULL OR time_window IN "
            "('lifetime', 'calendar_month', 'rolling_7d')",
            name="ck_rules_time_window",
        ),
        CheckConstraint(
            "composite_operator IS NULL OR composite_operator IN ('AND', 'OR')",
            name="ck_rules_composite_operator",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Trigger conditions
    transaction_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    count_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    streak_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    streak_unit_window: Mapped[str | None] = mapped_column(String(20), nullable=True)
    min_amount: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    time_window: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Reward
    reward_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reward_value: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)

    # Recurrence
    stop_after_n_triggers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resets_after_trigger: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    # Campaign (deferred — schema only)
    campaign_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    campaign_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Composite (deferred — schema only)
    composite_operator: Mapped[str | None] = mapped_column(String(5), nullable=True)

    # Segment binding (deferred — segments table doesn't exist yet)
    segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class RuleCondition(Base):
    """Sub-conditions for composite rules (PRD §6.8). Phase C: schema only."""

    __tablename__ = "rule_conditions"

    id: Mapped[uuid.UUID] = uuid_pk()
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.id"), nullable=False, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    count_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    min_amount: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )


class UserRuleProgress(Base):
    """Per-user, per-rule progress tracker (PRD §6.8 + Pay-PRD-0590)."""

    __tablename__ = "user_rule_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "rule_id", name="uq_user_rule_progress"),
        CheckConstraint(
            "status IN ('active', 'completed', 'deactivated')",
            name="ck_user_rule_progress_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.id"), nullable=False
    )
    current_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    current_streak: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    trigger_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_qualifying_event_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    window_start: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    updated_at: Mapped[datetime] = updated_at_col()

    rule: Mapped[Rule] = relationship()
