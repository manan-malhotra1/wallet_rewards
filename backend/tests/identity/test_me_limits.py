"""My limits — the signed-in user's wallet send/receive consumption vs caps.

`GET /api/v1/identity/me/limits` returns, per financial-wallet currency, how much
of the rolling daily/weekly/monthly SEND and RECEIVE caps the caller has consumed
alongside the configured caps (null cap = no limit). It reuses the same limits
machinery the money paths enforce.

Covers:
  - A user with a wallet + a WalletLimitConfig gets per-window consumed + caps;
    a COMPLETED send is reflected in send/daily consumed_value + consumed_count.
  - A wallet with NO limit config still returns a row, all caps null, no crash.
  - Tenant isolation — only the caller's own-tenant wallet + config are read.
  - 401 without a session token.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _seed_movement(
    session: AsyncSession,
    tenant_id,
    wallet_id,
    sink_id,
    *,
    principal: str,
    entry_type: str,
) -> None:
    """Seed one balanced COMPLETED transaction with a leg on the user's wallet.

    `entry_type` ENTRY_DEBIT models a send (money out), ENTRY_CREDIT a receive.
    Dated one hour ago so it lands inside every rolling window (24h/7d/30d).
    """
    principal_d = Decimal(principal)
    txn = Transaction(
        tenant_id=tenant_id,
        idempotency_key=f"mv-{uuid4().hex}",
        transaction_type="p2p",
        status=TXN_STATUS_COMPLETED,
        amount=principal_d,
        currency="ZAR",
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    session.add(txn)
    await session.flush()
    other_type = ENTRY_CREDIT if entry_type == ENTRY_DEBIT else ENTRY_DEBIT
    session.add(
        LedgerEntry(
            transaction_id=txn.id,
            account_id=wallet_id,
            entry_type=entry_type,
            amount=principal_d,
            currency="ZAR",
            status=ENTRY_STATUS_COMPLETED,
        )
    )
    session.add(
        LedgerEntry(
            transaction_id=txn.id,
            account_id=sink_id,
            entry_type=other_type,
            amount=principal_d,
            currency="ZAR",
            status=ENTRY_STATUS_COMPLETED,
        )
    )
    await session.commit()


async def _sink(session: AsyncSession, tenant_id) -> Account:
    """The tenant's pre-funded cash float, carrying the other leg of movements."""
    from app.modules.payments.service import get_or_create_system_cash_inflow

    return await get_or_create_system_cash_inflow(session, tenant_id, "ZAR")


@pytest.mark.asyncio
async def test_me_limits_reports_consumed_and_caps(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a user sees how much of their send/receive limits they've used and the caps."""
    sink = await _sink(db_session, test_tenant.id)
    await _seed_movement(
        db_session, test_tenant.id, user_wallet.id, sink.id, principal="100", entry_type=ENTRY_DEBIT
    )
    db_session.add(
        WalletLimitConfig(
            tenant_id=test_tenant.id,
            currency="ZAR",
            send_daily_count_cap=5,
            send_daily_value_cap=Decimal("1000"),
            receive_monthly_value_cap=Decimal("2000"),
        )
    )
    await db_session.commit()

    response = await async_client.get("/api/v1/identity/me/limits", headers=alice_auth_header)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["currency"] == "ZAR"

    # The seeded send is reflected in the send/daily consumption.
    send_daily = row["send"]["daily"]
    assert send_daily["consumed_count"] == 1
    assert Decimal(send_daily["consumed_value"]) == Decimal("100")
    assert send_daily["cap_count"] == 5
    assert Decimal(send_daily["cap_value"]) == Decimal("1000")

    # No receive activity; the configured monthly receive cap surfaces, the
    # unconfigured daily receive count cap is null ("no limit").
    receive = row["receive"]
    assert receive["daily"]["consumed_count"] == 0
    assert receive["daily"]["cap_count"] is None
    assert Decimal(receive["monthly"]["cap_value"]) == Decimal("2000")


@pytest.mark.asyncio
async def test_me_limits_no_config_returns_null_caps(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a wallet with no configured limits still shows usage with 'no limit' caps."""
    response = await async_client.get("/api/v1/identity/me/limits", headers=alice_auth_header)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    for direction in ("send", "receive"):
        for window in ("daily", "weekly", "monthly"):
            cell = row[direction][window]
            assert cell["cap_count"] is None
            assert cell["cap_value"] is None
            assert cell["consumed_count"] == 0
            assert Decimal(cell["consumed_value"]) == Decimal("0")


@pytest.mark.asyncio
async def test_me_limits_does_not_leak_other_tenant_config(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a user's limits reflect only their own tenant's config, never another's."""
    # A ZAR config exists ONLY in the other tenant — it must not bleed into the
    # caller's view. The caller's own tenant has no config → caps stay null.
    db_session.add(
        WalletLimitConfig(
            tenant_id=other_tenant.id,
            currency="ZAR",
            send_daily_count_cap=1,
            send_daily_value_cap=Decimal("1"),
        )
    )
    await db_session.commit()

    response = await async_client.get("/api/v1/identity/me/limits", headers=alice_auth_header)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["currency"] == "ZAR"
    assert rows[0]["send"]["daily"]["cap_count"] is None
    assert rows[0]["send"]["daily"]["cap_value"] is None


@pytest.mark.asyncio
async def test_me_limits_no_token_is_401(async_client: AsyncClient) -> None:
    """Verify viewing limit consumption requires signing in."""
    response = await async_client.get("/api/v1/identity/me/limits")
    assert response.status_code == 401
