"""Wallet limits — money going out.

`check_wallet_send_limits` enforces per-(tenant, currency) rolling
daily/weekly/monthly caps on the count + principal value a user sends from
their financial wallet, across every service. A "send" is a COMPLETED
transaction with a DEBIT leg on the wallet; the principal (transactions.amount)
is summed, fee legs excluded.

Sends are seeded as balanced transactions with an explicit `created_at` and a
fixed `now` anchor so windows are deterministic. Wallet limit configs are
inserted directly (admin CRUD lands in 7.10).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.service import check_wallet_send_limits
from app.shared.exceptions import WalletSendLimitExceeded
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
    """A system account to carry the CREDIT side of seeded sends (keeps balance).

    Uses get-or-create so it reuses the tenant's pre-funded cash float rather than
    constructing a second system_cash_inflow row (unique index).
    """
    from app.modules.payments.service import get_or_create_system_cash_inflow

    return await get_or_create_system_cash_inflow(session, tenant_id, "ZAR")


async def _seed_config(session: AsyncSession, tenant_id, **caps) -> None:
    """Insert a ZAR wallet limit config with the given caps and commit."""
    session.add(WalletLimitConfig(tenant_id=tenant_id, currency="ZAR", **caps))
    await session.commit()


async def _seed_send(
    session: AsyncSession,
    tenant_id,
    wallet_id,
    sink_id,
    *,
    principal: str,
    age_days: float,
    fee: str = "0",
    transaction_type: str = "p2p",
) -> None:
    """Seed one balanced COMPLETED send: DEBIT wallet (principal [+fee]),
    CREDIT sink (principal+fee). amount = principal (the fee is a separate leg)."""
    principal_d = Decimal(principal)
    fee_d = Decimal(fee)
    txn = Transaction(
        tenant_id=tenant_id,
        idempotency_key=f"send-{uuid4().hex}",
        transaction_type=transaction_type,
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
            account_id=wallet_id,
            entry_type=ENTRY_DEBIT,
            amount=principal_d,
            currency="ZAR",
            status=ENTRY_STATUS_COMPLETED,
        )
    )
    if fee_d > 0:
        session.add(
            LedgerEntry(
                transaction_id=txn.id,
                account_id=wallet_id,
                entry_type=ENTRY_DEBIT,
                amount=fee_d,
                currency="ZAR",
                status=ENTRY_STATUS_COMPLETED,
            )
        )
    session.add(
        LedgerEntry(
            transaction_id=txn.id,
            account_id=sink_id,
            entry_type=ENTRY_CREDIT,
            amount=principal_d + fee_d,
            currency="ZAR",
            status=ENTRY_STATUS_COMPLETED,
        )
    )
    await session.commit()


async def _check(session: AsyncSession, tenant_id, user_id, amount="10") -> None:
    await check_wallet_send_limits(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        currency="ZAR",
        amount=Decimal(amount),
        now=ANCHOR,
    )


@pytest.mark.asyncio
async def test_no_wallet_config_is_pass_through(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Verify money going out is allowed through when no wallet limit is configured."""
    await _check(db_session, test_tenant.id, test_user.id, amount="9999999")


@pytest.mark.asyncio
async def test_send_daily_count_cap_enforced(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Verify a customer cannot exceed the number of times they can send money in a day."""
    sink = await _make_sink(db_session, test_tenant.id)
    for _ in range(2):
        await _seed_send(
            db_session, test_tenant.id, user_wallet.id, sink.id, principal="100", age_days=0.2
        )
    await _seed_config(db_session, test_tenant.id, send_daily_count_cap=2)

    with pytest.raises(WalletSendLimitExceeded) as exc:
        await _check(db_session, test_tenant.id, test_user.id)
    assert exc.value.error_code == "wallet_send_daily_count_exceeded"


@pytest.mark.asyncio
async def test_send_weekly_value_cap_enforced(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Verify a customer cannot exceed the total amount they can send in a week."""
    sink = await _make_sink(db_session, test_tenant.id)
    await _seed_send(
        db_session, test_tenant.id, user_wallet.id, sink.id, principal="90", age_days=2
    )
    await _seed_config(db_session, test_tenant.id, send_weekly_value_cap=Decimal("100"))

    with pytest.raises(WalletSendLimitExceeded) as exc:
        await _check(db_session, test_tenant.id, test_user.id, amount="20")
    assert exc.value.error_code == "wallet_send_weekly_value_exceeded"


@pytest.mark.asyncio
async def test_send_value_excludes_fees(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Verify fees are not counted toward how much a customer can send."""
    sink = await _make_sink(db_session, test_tenant.id)
    await _seed_send(
        db_session, test_tenant.id, user_wallet.id, sink.id, principal="90", age_days=2, fee="50"
    )
    await _seed_config(db_session, test_tenant.id, send_weekly_value_cap=Decimal("100"))

    # principal-only total is 90; 90 + 10 = 100, not > 100 → passes. (If the
    # R50 fee were counted, the existing total would be 140 and this would fail.)
    await _check(db_session, test_tenant.id, test_user.id, amount="10")


@pytest.mark.asyncio
async def test_send_with_fee_counts_as_one_transaction(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Verify a single send counts once toward the customer's limit even when a fee is charged."""
    sink = await _make_sink(db_session, test_tenant.id)
    await _seed_send(
        db_session, test_tenant.id, user_wallet.id, sink.id, principal="10", age_days=0.2, fee="2"
    )
    await _seed_config(db_session, test_tenant.id, send_daily_count_cap=1)

    # One prior send (two debit legs) = count 1; the next send is the 2nd → 429.
    with pytest.raises(WalletSendLimitExceeded):
        await _check(db_session, test_tenant.id, test_user.id)


@pytest.mark.asyncio
async def test_send_counts_across_services(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Verify a customer's send limit applies across all the ways they can send money."""
    sink = await _make_sink(db_session, test_tenant.id)
    await _seed_send(
        db_session,
        test_tenant.id,
        user_wallet.id,
        sink.id,
        principal="50",
        age_days=0.2,
        transaction_type="p2p",
    )
    await _seed_send(
        db_session,
        test_tenant.id,
        user_wallet.id,
        sink.id,
        principal="50",
        age_days=0.3,
        transaction_type="airtime_recharge",
    )
    await _seed_config(db_session, test_tenant.id, send_daily_count_cap=2)

    with pytest.raises(WalletSendLimitExceeded):
        await _check(db_session, test_tenant.id, test_user.id)


@pytest.mark.asyncio
async def test_send_window_excludes_older_than_7d(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, user_wallet: Account
) -> None:
    """Verify money sent more than a week ago no longer counts toward the weekly limit."""
    sink = await _make_sink(db_session, test_tenant.id)
    await _seed_send(
        db_session, test_tenant.id, user_wallet.id, sink.id, principal="100", age_days=8
    )
    await _seed_config(db_session, test_tenant.id, send_weekly_count_cap=1)

    # The only send is out of the 7d window → in-window count 0 → passes.
    await _check(db_session, test_tenant.id, test_user.id)


@pytest.mark.asyncio
async def test_wallet_send_config_does_not_leak_across_tenants(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant, test_user: User
) -> None:
    """Verify one tenant cannot see or use another tenant's wallet limits."""
    await _seed_config(db_session, other_tenant.id, send_daily_count_cap=0)

    # test_user is in test_tenant, which has no wallet config → pass-through,
    # even though other_tenant has a zero cap.
    await _check(db_session, test_tenant.id, test_user.id, amount="9999999")
