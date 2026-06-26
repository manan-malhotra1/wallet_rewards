"""Tests for rolling weekly + monthly service-wise limit caps (WAL-234).

`check_limits` enforces daily (24h), weekly (7d), and monthly (30d) rolling
count + value caps. These tests drive the new weekly/monthly windows and the
window-boundary correctness. Configs are inserted directly (the admin schema
gains weekly/monthly fields in 7.10); transactions are seeded with explicit
`created_at` and a fixed `now` anchor so windows are deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.service import check_limits
from app.shared.exceptions import (
    MonthlyCountExceeded,
    WeeklyCountExceeded,
    WeeklyValueExceeded,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    TXN_STATUS_COMPLETED,
    LimitConfig,
    Tenant,
    Transaction,
    User,
)

# Fixed point so rolling windows are deterministic across runs.
ANCHOR = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


async def _seed_config(session: AsyncSession, tenant_id, **caps) -> None:
    """Insert a p2p/ZAR limit config with the given window caps and commit."""
    session.add(
        LimitConfig(
            tenant_id=tenant_id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            **caps,
        )
    )
    await session.commit()


async def _seed_txns(
    session: AsyncSession, tenant_id, user_id, *, ages_days: list[float], amount="100"
) -> None:
    """Seed COMPLETED p2p txns at ANCHOR minus each age (in days)."""
    for age in ages_days:
        session.add(
            Transaction(
                tenant_id=tenant_id,
                idempotency_key=f"seed-{uuid4().hex}",
                transaction_type="p2p",
                status=TXN_STATUS_COMPLETED,
                initiated_by=user_id,
                amount=Decimal(amount),
                currency="ZAR",
                created_at=ANCHOR - timedelta(days=age),
            )
        )
    await session.commit()


async def _check(session: AsyncSession, tenant_id, user_id, amount="10") -> None:
    """Run check_limits for a p2p/ZAR transfer anchored at ANCHOR."""
    await check_limits(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        amount=Decimal(amount),
        now=ANCHOR,
    )


@pytest.mark.asyncio
async def test_weekly_count_cap_enforced(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Two txns inside 7d with weekly_count_cap=2 → the 3rd raises 429."""
    await _seed_txns(db_session, test_tenant.id, test_user.id, ages_days=[1, 6])
    await _seed_config(db_session, test_tenant.id, weekly_count_cap=2)

    with pytest.raises(WeeklyCountExceeded):
        await _check(db_session, test_tenant.id, test_user.id)


@pytest.mark.asyncio
async def test_weekly_value_cap_enforced(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """R90 already moved this week + R20 now > weekly_value_cap=R100 → 429."""
    await _seed_txns(db_session, test_tenant.id, test_user.id, ages_days=[2], amount="90")
    await _seed_config(db_session, test_tenant.id, weekly_value_cap=Decimal("100"))

    with pytest.raises(WeeklyValueExceeded):
        await _check(db_session, test_tenant.id, test_user.id, amount="20")


@pytest.mark.asyncio
async def test_monthly_count_cap_enforced(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Three txns inside 30d with monthly_count_cap=3 → the 4th raises 429."""
    await _seed_txns(db_session, test_tenant.id, test_user.id, ages_days=[10, 20, 29])
    await _seed_config(db_session, test_tenant.id, monthly_count_cap=3)

    with pytest.raises(MonthlyCountExceeded):
        await _check(db_session, test_tenant.id, test_user.id)


@pytest.mark.asyncio
async def test_weekly_window_excludes_txns_older_than_7d(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """A txn 8 days old does NOT count toward the weekly cap (boundary)."""
    await _seed_txns(db_session, test_tenant.id, test_user.id, ages_days=[8])
    await _seed_config(db_session, test_tenant.id, weekly_count_cap=1)

    # Only the out-of-window txn exists → in-window count is 0, so this passes.
    await _check(db_session, test_tenant.id, test_user.id)


@pytest.mark.asyncio
async def test_monthly_cap_catches_txns_outside_the_weekly_window(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Txns 10/20 days old skip the weekly cap but trip the monthly cap."""
    await _seed_txns(db_session, test_tenant.id, test_user.id, ages_days=[10, 20])
    await _seed_config(db_session, test_tenant.id, weekly_count_cap=5, monthly_count_cap=2)

    # Weekly window sees 0 (both txns >7d old) → passes weekly; monthly sees 2
    # → +1 exceeds the cap of 2.
    with pytest.raises(MonthlyCountExceeded):
        await _check(db_session, test_tenant.id, test_user.id)


@pytest.mark.asyncio
async def test_unconfigured_windows_are_not_checked(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """With only a weekly cap set, a same-day flurry never trips a daily cap."""
    await _seed_txns(db_session, test_tenant.id, test_user.id, ages_days=[0.1, 0.2, 0.3])
    await _seed_config(db_session, test_tenant.id, weekly_count_cap=10)

    # 3 txns today, but daily_count_cap is NULL and weekly cap (10) not reached.
    await _check(db_session, test_tenant.id, test_user.id)
