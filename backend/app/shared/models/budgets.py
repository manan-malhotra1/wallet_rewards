"""RewardBudget model — Phase G.1 (Module 7+ control).

Caps how much can be issued per (tenant, scope, currency, window). The
`issue_points_reward` service consults this BEFORE writing the ledger.
Consumption is computed live from `reward_events` — no separate counter
column to keep in sync.

Two scopes:
  - `tenant`-scoped: one row per (tenant, currency, window_type) when
    `scope_id IS NULL`. Caps total reward issuance for the tenant.
  - `rule`-scoped:   one row per (tenant, rule_id, currency, window_type)
    when `scope_id` is set. Caps issuance for that specific rule.

Two unique partial indexes enforce the "one budget per slot" invariant
(Postgres treats NULLs as distinct on plain UNIQUE, so we split).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# Window types — keep in sync with the CHECK constraint below.
BUDGET_WINDOW_ROLLING_24H = "rolling_24h"
BUDGET_WINDOW_ROLLING_7D = "rolling_7d"
BUDGET_WINDOW_CALENDAR_MONTH = "calendar_month"
BUDGET_WINDOW_LIFETIME = "lifetime"

BUDGET_SCOPE_TENANT = "tenant"
BUDGET_SCOPE_RULE = "rule"

BUDGET_STATUS_ACTIVE = "active"
BUDGET_STATUS_PAUSED = "paused"


class RewardBudget(Base):
    """A cap on reward issuance for a tenant or a specific rule."""

    __tablename__ = "reward_budgets"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('tenant', 'rule')",
            name="ck_reward_budgets_scope_type",
        ),
        CheckConstraint(
            "window_type IN ("
            "'rolling_24h', 'rolling_7d', 'calendar_month', 'lifetime'"
            ")",
            name="ck_reward_budgets_window_type",
        ),
        CheckConstraint(
            "status IN ('active', 'paused')",
            name="ck_reward_budgets_status",
        ),
        CheckConstraint(
            "cap_amount > 0",
            name="ck_reward_budgets_cap_positive",
        ),
        # Tenant-scoped budget: one per (tenant, currency, window).
        Index(
            "uq_reward_budgets_tenant_scope",
            "tenant_id",
            "currency",
            "window_type",
            unique=True,
            postgresql_where=text("scope_id IS NULL"),
        ),
        # Rule-scoped budget: one per (tenant, rule, currency, window).
        Index(
            "uq_reward_budgets_rule_scope",
            "tenant_id",
            "scope_id",
            "currency",
            "window_type",
            unique=True,
            postgresql_where=text("scope_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # NULL when scope_type='tenant'; FK to rules.id when scope_type='rule'.
    # Not a hard FK constraint because budgets can outlive deleted rules
    # for audit purposes — soft reference only.
    scope_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    window_type: Mapped[str] = mapped_column(String(20), nullable=False)
    cap_amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
