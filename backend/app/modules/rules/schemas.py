"""Pydantic v2 schemas for the rules module."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

RuleType = Literal[
    "milestone",
    "streak",
    "first_time",
    "value_based",
    "composite",
    "campaign",
    "referral",
]
RewardType = Literal["points", "cashback"]
TimeWindow = Literal["lifetime", "calendar_month", "rolling_7d"]
StreakUnit = Literal["day", "week"]


class RuleCreateRequest(BaseModel):
    """Rule creation payload — Phase C (first_time, milestone) +
    Epic 10 expansion (value_based, campaign, streak).

    The 3 remaining rule types (composite, referral) still persist OK
    but their evaluator branches are deferred to follow-up commits.
    """

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    rule_type: RuleType
    transaction_type: str | None = Field(default=None, max_length=50)
    count_threshold: int | None = Field(default=None, ge=1)
    time_window: TimeWindow | None = None
    min_amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    # Epic 10 — streak fields.
    streak_units: int | None = Field(default=None, ge=2)
    streak_unit_window: StreakUnit | None = None
    # Epic 10 — campaign date gates.
    campaign_start_date: date | None = None
    campaign_end_date: date | None = None

    reward_type: RewardType
    reward_value: Decimal = Field(gt=Decimal("0"))
    stop_after_n_triggers: int | None = Field(default=None, ge=1)
    resets_after_trigger: bool = True

    @model_validator(mode="after")
    def _validate_consistency(self) -> RuleCreateRequest:
        """Cross-field validation that matches the evaluator's assumptions.

        Per-type rules:
          - milestone: needs count_threshold
          - first_time: must NOT specify count_threshold
          - first_time / milestone / streak / value_based: need transaction_type
          - streak: needs streak_units (>= 2) and streak_unit_window
          - value_based: needs min_amount > 0
          - campaign: needs both start + end dates with start <= end
        """
        if self.rule_type == "milestone" and self.count_threshold is None:
            raise ValueError("milestone rules require count_threshold >= 1")
        if self.rule_type == "first_time" and self.count_threshold is not None:
            raise ValueError("first_time rules must NOT specify count_threshold")
        if (
            self.rule_type in ("first_time", "milestone", "streak", "value_based")
            and not self.transaction_type
        ):
            raise ValueError(f"{self.rule_type} rules require a transaction_type")
        if self.rule_type == "streak":
            if self.streak_units is None or self.streak_unit_window is None:
                raise ValueError(
                    "streak rules require streak_units (>= 2) and "
                    "streak_unit_window ('day' or 'week')"
                )
        if self.rule_type == "value_based":
            if self.min_amount is None or self.min_amount <= 0:
                raise ValueError("value_based rules require min_amount > 0")
        if self.rule_type == "campaign":
            if self.campaign_start_date is None or self.campaign_end_date is None:
                raise ValueError(
                    "campaign rules require both campaign_start_date and campaign_end_date"
                )
            if self.campaign_start_date > self.campaign_end_date:
                raise ValueError("campaign_start_date must be on or before campaign_end_date")
            if not self.transaction_type:
                raise ValueError("campaign rules require a transaction_type")
        return self


class RuleOut(BaseModel):
    """Rule resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    rule_type: str
    transaction_type: str | None
    count_threshold: int | None
    min_amount: Decimal | None = None
    streak_units: int | None = None
    streak_unit_window: str | None = None
    campaign_start_date: date | None = None
    campaign_end_date: date | None = None
    reward_type: str
    reward_value: Decimal
    stop_after_n_triggers: int | None
    resets_after_trigger: bool
    status: str


BudgetScope = Literal["none", "tenant_only", "rule_only", "both"]


class RuleUpdateRequest(BaseModel):
    """Partial update — admin can change description, reward_value, status.

    Fields that change the rule's TYPE or its trigger conditions are
    intentionally not editable: an in-flight `user_rule_progress` row
    assumes those values are stable. Operators wanting to change them
    should deactivate this rule and create a new one.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    reward_value: Decimal | None = Field(default=None, gt=Decimal("0"))
    stop_after_n_triggers: int | None = Field(default=None, ge=1)
    status: Literal["active", "inactive"] | None = None


class RulePerformanceOut(BaseModel):
    """Campaign performance metrics for a single rule.

    Computed live from `reward_events` — no separate counter table. The
    UI surfaces these on the campaigns list and detail drawer.

    Fields:
        rule_id: The rule (campaign) these metrics describe.
        total_fires: Count of every issuance for this rule. A user who
            triggered the rule 3 times contributes 3 to this number.
        unique_users_rewarded: DISTINCT user_id count — how many separate
            people have been rewarded at least once.
        total_reward_value: SUM of every reward_value issued. Sum is
            in the rule's reward_type unit (points or cashback currency).
        first_fired_at / last_fired_at: Earliest and latest reward_event
            timestamps. Null when the rule has never fired.
        budget_scope: Which budgets (if any) gate this campaign.
            `none` = uncapped; `tenant_only` = only the tenant-wide cap;
            `rule_only` = only a per-rule cap; `both` = layered (both
            must pass).
    """

    model_config = ConfigDict(from_attributes=True)

    rule_id: UUID
    total_fires: int = Field(ge=0)
    unique_users_rewarded: int = Field(ge=0)
    total_reward_value: Decimal
    first_fired_at: datetime | None
    last_fired_at: datetime | None
    budget_scope: BudgetScope = "none"
