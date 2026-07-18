"""Tests for wallet RECEIVE limits + max balance (WAL-236).

`check_wallet_receive_limits` guards a credit before it lands on a user's
financial wallet: a max-balance ceiling and rolling daily/weekly/monthly
receive caps (count + principal). `recipient_facing=True` (P2P credit to
someone else) surfaces detail-free `recipient_*` errors instead of the
owner-facing cap.

Receives are seeded as balanced transactions (DEBIT sink, CREDIT wallet) with
an explicit `created_at` and a fixed `now` anchor.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.service import check_wallet_receive_limits
from app.shared.exceptions import (
    MaxBalanceExceeded,
    RecipientLimitReached,
    RecipientMaxBalanceExceeded,
    WalletReceiveLimitExceeded,
)
from app.shared.models import (
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    TXN_STATUS_COMPLETED,
    Account,
    LedgerEntry,
    Tenant,
    Transaction,
    User,
    WalletLimitConfig,
)

ANCHOR = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


async def _make_sink(session: AsyncSession, tenant_id) -> Account:
    """A system account to carry the DEBIT side of seeded receives.

    Uses get-or-create so it reuses the tenant's pre-funded cash float rather than
    constructing a second system_cash_inflow row (unique index).
    """
    from app.modules.payments.service import get_or_create_system_cash_inflow

    return await get_or_create_system_cash_inflow(session, tenant_id, "ZAR")


async def _seed_config(session: AsyncSession, tenant_id, **caps) -> None:
    """Insert a ZAR wallet limit config with the given caps and commit."""
    session.add(WalletLimitConfig(tenant_id=tenant_id, currency="ZAR", **caps))
    await session.commit()


async def _seed_receive(
    session: AsyncSession,
    tenant_id,
    wallet_id,
    sink_id,
    *,
    principal: str,
    age_days: float,
) -> None:
    """Seed one balanced COMPLETED receive: DEBIT sink, CREDIT wallet (principal)."""
    principal_d = Decimal(principal)
    txn = Transaction(
        tenant_id=tenant_id,
        idempotency_key=f"recv-{uuid4().hex}",
        transaction_type="fund",
        status=TXN_STATUS_COMPLETED,
        amount=principal_d,
        currency="ZAR",
        created_at=ANCHOR - timedelta(days=age_days),
    )
    session.add(txn)
    await session.flush()
    session.add(
        LedgerEntry(
            transaction_id=txn.id,
            account_id=sink_id,
            entry_type=ENTRY_DEBIT,
            amount=principal_d,
            currency="ZAR",
            status=ENTRY_STATUS_COMPLETED,
        )
    )
    session.add(
        LedgerEntry(
            transaction_id=txn.id,
            account_id=wallet_id,
            entry_type=ENTRY_CREDIT,
            amount=principal_d,
            currency="ZAR",
            status=ENTRY_STATUS_COMPLETED,
        )
    )
    await session.commit()


async def _check(
    session: AsyncSession, tenant_id, user_id, *, amount="10", recipient_facing=False
) -> None:
    await check_wallet_receive_limits(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        currency="ZAR",
        amount=Decimal(amount),
        recipient_facing=recipient_facing,
        now=ANCHOR,
    )


@pytest.mark.asyncio
async def test_no_wallet_config_is_pass_through(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """No wallet limit config → no-op even for a huge credit."""
    await _check(db_session, test_tenant.id, test_user.id, amount="9999999")


@pytest.mark.asyncio
async def test_max_balance_blocks_credit_over_cap(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """balance 80 + credit 30 > max_balance 100 → 409 max_balance_exceeded."""
    sink = await _make_sink(db_session, test_tenant.id)
    await _seed_receive(
        db_session, test_tenant.id, user_wallet.id, sink.id, principal="80", age_days=2
    )
    await _seed_config(db_session, test_tenant.id, max_balance=Decimal("100"))

    with pytest.raises(MaxBalanceExceeded) as exc:
        await _check(db_session, test_tenant.id, test_user.id, amount="30")
    assert exc.value.error_code == "max_balance_exceeded"


@pytest.mark.asyncio
async def test_credit_that_fits_under_max_balance_passes(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """balance 80 + credit 20 = 100, not > 100 → passes."""
    sink = await _make_sink(db_session, test_tenant.id)
    await _seed_receive(
        db_session, test_tenant.id, user_wallet.id, sink.id, principal="80", age_days=2
    )
    await _seed_config(db_session, test_tenant.id, max_balance=Decimal("100"))

    await _check(db_session, test_tenant.id, test_user.id, amount="20")


@pytest.mark.asyncio
async def test_receive_daily_count_cap_enforced(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Two receives today with receive_daily_count_cap=2 → the 3rd raises 429."""
    sink = await _make_sink(db_session, test_tenant.id)
    for _ in range(2):
        await _seed_receive(
            db_session, test_tenant.id, user_wallet.id, sink.id, principal="100", age_days=0.2
        )
    await _seed_config(db_session, test_tenant.id, receive_daily_count_cap=2)

    with pytest.raises(WalletReceiveLimitExceeded) as exc:
        await _check(db_session, test_tenant.id, test_user.id)
    assert exc.value.error_code == "wallet_receive_daily_count_exceeded"


@pytest.mark.asyncio
async def test_receive_weekly_value_cap_enforced(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """R90 received this week + R20 now > receive_weekly_value_cap=R100 → 429."""
    sink = await _make_sink(db_session, test_tenant.id)
    await _seed_receive(
        db_session, test_tenant.id, user_wallet.id, sink.id, principal="90", age_days=2
    )
    await _seed_config(db_session, test_tenant.id, receive_weekly_value_cap=Decimal("100"))

    with pytest.raises(WalletReceiveLimitExceeded) as exc:
        await _check(db_session, test_tenant.id, test_user.id, amount="20")
    assert exc.value.error_code == "wallet_receive_weekly_value_exceeded"


@pytest.mark.asyncio
async def test_recipient_facing_max_balance_is_detail_free(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """P2P credit breaching recipient max balance → recipient_max_balance_exceeded."""
    sink = await _make_sink(db_session, test_tenant.id)
    await _seed_receive(
        db_session, test_tenant.id, user_wallet.id, sink.id, principal="80", age_days=2
    )
    await _seed_config(db_session, test_tenant.id, max_balance=Decimal("100"))

    with pytest.raises(RecipientMaxBalanceExceeded) as exc:
        await _check(db_session, test_tenant.id, test_user.id, amount="30", recipient_facing=True)
    assert exc.value.error_code == "recipient_max_balance_exceeded"


@pytest.mark.asyncio
async def test_recipient_facing_cap_raises_recipient_limit_reached(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """P2P credit breaching a recipient receive cap → recipient_limit_reached."""
    sink = await _make_sink(db_session, test_tenant.id)
    for _ in range(2):
        await _seed_receive(
            db_session, test_tenant.id, user_wallet.id, sink.id, principal="10", age_days=0.2
        )
    await _seed_config(db_session, test_tenant.id, receive_daily_count_cap=2)

    with pytest.raises(RecipientLimitReached) as exc:
        await _check(db_session, test_tenant.id, test_user.id, recipient_facing=True)
    assert exc.value.error_code == "recipient_limit_reached"


@pytest.mark.asyncio
async def test_receive_window_excludes_older_than_7d(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """A receive 8 days old does NOT count toward the weekly receive cap."""
    sink = await _make_sink(db_session, test_tenant.id)
    await _seed_receive(
        db_session, test_tenant.id, user_wallet.id, sink.id, principal="100", age_days=8
    )
    await _seed_config(db_session, test_tenant.id, receive_weekly_count_cap=1)

    await _check(db_session, test_tenant.id, test_user.id)


@pytest.mark.asyncio
async def test_wallet_receive_config_does_not_leak_across_tenants(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant, test_user: User
) -> None:
    """A wallet limit config in another tenant doesn't apply to this caller."""
    await _seed_config(db_session, other_tenant.id, max_balance=Decimal("1"))

    await _check(db_session, test_tenant.id, test_user.id, amount="9999999")
