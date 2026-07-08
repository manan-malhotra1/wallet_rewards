"""Tests for the reward-budgets service (Phase G.1)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.budgets.schemas import BudgetCreateRequest
from app.modules.budgets.service import (
    check_budget_available,
    create_budget,
    list_budgets_for_tenant,
)
from app.shared.exceptions import BudgetExceeded
from app.shared.models import Tenant


@pytest.mark.asyncio
async def test_no_budgets_is_pass_through(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """When no budget rows exist, check_budget_available is a no-op."""
    await check_budget_available(
        db_session,
        tenant_id=test_tenant.id,
        rule_id=uuid4(),
        currency="PTS",
        amount=Decimal("9999"),
    )


@pytest.mark.asyncio
async def test_tenant_scope_lifetime_budget_blocks_overrun(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A tenant-scoped lifetime budget of 500 PTS rejects a 600 PTS issuance."""
    await create_budget(
        db_session,
        BudgetCreateRequest(
            tenant_id=test_tenant.id,
            scope_type="tenant",
            currency="PTS",
            window_type="lifetime",
            cap_amount=Decimal("500"),
        ),
    )
    with pytest.raises(BudgetExceeded):
        await check_budget_available(
            db_session,
            tenant_id=test_tenant.id,
            rule_id=uuid4(),
            currency="PTS",
            amount=Decimal("600"),
        )


@pytest.mark.asyncio
async def test_list_budgets_returns_consumption(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """List endpoint returns consumed + remaining + percent_consumed."""
    await create_budget(
        db_session,
        BudgetCreateRequest(
            tenant_id=test_tenant.id,
            scope_type="tenant",
            currency="PTS",
            window_type="lifetime",
            cap_amount=Decimal("1000"),
        ),
    )
    payload = await list_budgets_for_tenant(db_session, test_tenant.id)
    assert len(payload) == 1
    entry = payload[0]
    assert entry.budget.window_type == "lifetime"
    assert entry.consumed_amount == Decimal("0")
    assert entry.remaining_amount == Decimal("1000")
    assert entry.percent_consumed == 0.0
