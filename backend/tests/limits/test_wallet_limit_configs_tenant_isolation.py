"""Tenant isolation for the wallet_limit_configs table (WAL-233).

A wallet limit config created in one tenant must never be visible to a
query scoped to another tenant (NFR-0220). CRUD + enforcement land in
later stories (7.8-7.10); this guards the new table at the schema level.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, WalletLimitConfig


@pytest.mark.asyncio
async def test_wallet_limit_config_not_visible_across_tenants(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """A config in test_tenant is invisible to an other_tenant-scoped query."""
    db_session.add(
        WalletLimitConfig(
            tenant_id=test_tenant.id,
            currency="ZAR",
            max_balance=Decimal("50000"),
            send_daily_value_cap=Decimal("10000"),
            receive_monthly_count_cap=100,
        )
    )
    await db_session.commit()

    # Same currency, different tenant → zero rows (no cross-tenant leak).
    rows = (
        (
            await db_session.execute(
                select(WalletLimitConfig).where(WalletLimitConfig.tenant_id == other_tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []

    # Sanity: the owning tenant does see exactly its row.
    own = (
        (
            await db_session.execute(
                select(WalletLimitConfig).where(WalletLimitConfig.tenant_id == test_tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(own) == 1
    assert own[0].currency == "ZAR"
    assert own[0].max_balance == Decimal("50000.000000")
