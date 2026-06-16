"""Pydantic v2 schemas for the rules module."""
from __future__ import annotations

from datetime import datetime
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


class RuleCreateRequest(BaseModel):
    """Test-only rule creation payload.

    Phase C supports `first_time` and `milestone` end-to-end. Other types
    persist correctly but the evaluator does not fire them yet.
    """

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    rule_type: RuleType
    transaction_type: str | None = Field(default=None, max_length=50)
    count_threshold: int | None = Field(default=None, ge=1)
    time_window: TimeWindow | None = None
    min_amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    reward_type: RewardType
    reward_value: Decimal = Field(gt=Decimal("0"))
    stop_after_n_triggers: int | None = Field(default=None, ge=1)
    resets_after_trigger: bool = True

    @model_validator(mode="after")
    def _validate_consistency(self) -> RuleCreateRequest:
        """Cross-field validation that matches the evaluator's assumptions."""
        if self.rule_type == "milestone" and self.count_threshold is None:
            raise ValueError(
                "milestone rules require count_threshold >= 1",
            )
        if self.rule_type == "first_time" and self.count_threshold is not None:
            # First-time rules don't use count_threshold; warn via validation.
            raise ValueError(
                "first_time rules must NOT specify count_threshold",
            )
        if (
            self.rule_type in ("first_time", "milestone")
            and not self.transaction_type
        ):
            raise ValueError(
                f"{self.rule_type} rules require a transaction_type",
            )
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
    reward_type: str
    reward_value: Decimal
    stop_after_n_triggers: int | None
    resets_after_trigger: bool
    status: str


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
    """

    model_config = ConfigDict(from_attributes=True)

    rule_id: UUID
    total_fires: int = Field(ge=0)
    unique_users_rewarded: int = Field(ge=0)
    total_reward_value: Decimal
    first_fired_at: datetime | None
    last_fired_at: datetime | None
