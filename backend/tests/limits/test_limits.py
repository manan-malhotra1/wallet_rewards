"""Tests for the limits service (Phase G.2).

We test the service directly (faster + more focused than going through
the admin HTTP layer) and the integration via the p2p_transfer service
to confirm the orchestration honours limits.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.schemas import LimitConfigCreateRequest
from app.modules.limits.service import check_limits, create_limit_config
from app.shared.exceptions import (
    AmountAboveMax,
    AmountBelowMin,
    DailyCountExceeded,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Tenant,
    User,
)


@pytest.mark.asyncio
async def test_no_config_is_pass_through(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """When no limit config exists, check_limits is a no-op."""
    await check_limits(
        db_session,
        tenant_id=test_tenant.id,
        user_id=uuid4(),
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        amount=Decimal("9999999"),
    )


@pytest.mark.asyncio
async def test_amount_below_min_rejected(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Configuring min_amount=R 50 → R 10 transfer raises AmountBelowMin."""
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            min_amount=Decimal("50"),
        ),
    )
    with pytest.raises(AmountBelowMin):
        await check_limits(
            db_session,
            tenant_id=test_tenant.id,
            user_id=uuid4(),
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            amount=Decimal("10"),
        )


@pytest.mark.asyncio
async def test_amount_above_max_rejected(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """max_amount=R 1000 → R 5000 transfer raises AmountAboveMax."""
    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            max_amount=Decimal("1000"),
        ),
    )
    with pytest.raises(AmountAboveMax):
        await check_limits(
            db_session,
            tenant_id=test_tenant.id,
            user_id=uuid4(),
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            amount=Decimal("5000"),
        )


@pytest.mark.asyncio
async def test_daily_count_cap_enforced(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Once daily_count_cap=2 is reached, a 3rd transfer raises 429."""
    from app.shared.models import Transaction, TXN_STATUS_COMPLETED

    # `test_user` is a real DB row so the FK on `transactions.initiated_by`
    # resolves; uuid4() would FK-violate.
    user_id = test_user.id
    # Pre-seed 2 completed transactions in the rolling 24h window.
    for _ in range(2):
        db_session.add(
            Transaction(
                tenant_id=test_tenant.id,
                idempotency_key=f"seed-{uuid4().hex}",
                transaction_type="p2p",
                status=TXN_STATUS_COMPLETED,
                initiated_by=user_id,
                amount=Decimal("100"),
                currency="ZAR",
            )
        )
    await db_session.commit()

    await create_limit_config(
        db_session,
        LimitConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=2,
        ),
    )

    with pytest.raises(DailyCountExceeded):
        await check_limits(
            db_session,
            tenant_id=test_tenant.id,
            user_id=user_id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            amount=Decimal("10"),
        )
