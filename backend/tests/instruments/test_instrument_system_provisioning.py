"""System-account provisioning on instrument create (Epic 28, Story 28.1).

Creating a new currency must eagerly provision that currency's SYSTEM
accounts so it shows up complete on the System Wallets page, instead of
waiting for the first transaction to lazily create them. These tests pin:

  - a financial instrument provisions exactly the 5 core money system
    accounts (cash-inflow, fee, commission, tax-service, tax-commission);
  - a points instrument provisions system_points_issuance;
  - provisioning is idempotent (pre-seeded / double-create adds no dupes);
  - the lazy get-or-create path still returns the SAME row afterwards;
  - the `instrument.created` audit after_state carries `system_accounts`;
  - operator_adjustment is DELIBERATELY not provisioned here.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.service import get_or_create_system_cash_inflow
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    ACCOUNT_TYPE_TAX_COMMISSION,
    ACCOUNT_TYPE_TAX_SERVICE,
    Account,
    AuditLog,
    Tenant,
)

# The exact set provisioned for a financial_wallet currency.
_FINANCIAL_SYSTEM_TYPES = (
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_TAX_SERVICE,
    ACCOUNT_TYPE_TAX_COMMISSION,
)


async def _system_accounts(
    session: AsyncSession, tenant_id: str, currency: str, account_type: str
) -> list[Account]:
    """Return all system (user_id NULL) accounts of a type for a currency."""
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.account_type == account_type,
            Account.currency == currency,
            Account.user_id.is_(None),
        )
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_create_financial_instrument_provisions_five_system_accounts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A fresh financial currency gets exactly its 5 money system accounts."""
    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "KES",
            "symbol": "KSh",
            "display_name": "Kenyan Shilling",
            "account_type": "financial_wallet",
        },
    )
    assert resp.status_code == 201, resp.text

    for account_type in _FINANCIAL_SYSTEM_TYPES:
        rows = await _system_accounts(db_session, str(test_tenant.id), "KES", account_type)
        assert len(rows) == 1, f"expected one {account_type} for KES, got {len(rows)}"
        assert rows[0].user_id is None
        assert rows[0].currency == "KES"
        assert rows[0].account_type == account_type


@pytest.mark.asyncio
async def test_financial_instrument_does_not_provision_operator_adjustment(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """operator_adjustment (the named bank mirror) is intentionally excluded."""
    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "KES",
            "symbol": "KSh",
            "display_name": "Kenyan Shilling",
            "account_type": "financial_wallet",
        },
    )
    assert resp.status_code == 201, resp.text

    rows = await _system_accounts(
        db_session, str(test_tenant.id), "KES", ACCOUNT_TYPE_OPERATOR_ADJUSTMENT
    )
    assert rows == []


@pytest.mark.asyncio
async def test_create_points_instrument_provisions_points_issuance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A fresh points currency gets its system_points_issuance master."""
    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "STAR",
            "symbol": "*",
            "display_name": "Star Points",
            "account_type": "points_account",
        },
    )
    assert resp.status_code == 201, resp.text

    rows = await _system_accounts(
        db_session, str(test_tenant.id), "STAR", ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE
    )
    assert len(rows) == 1
    assert rows[0].user_id is None
    assert rows[0].currency == "STAR"

    # No money system accounts for a points currency.
    for account_type in _FINANCIAL_SYSTEM_TYPES:
        assert await _system_accounts(db_session, str(test_tenant.id), "STAR", account_type) == []


@pytest.mark.asyncio
async def test_points_instrument_reports_one_provisioned_account(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A points instrument audit records system_accounts == 1."""
    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "STAR",
            "symbol": "*",
            "display_name": "Star Points",
            "account_type": "points_account",
        },
    )
    assert resp.status_code == 201, resp.text
    instrument_id = resp.json()["id"]

    row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "instrument",
                AuditLog.entity_id == instrument_id,
                AuditLog.action == "instrument.created",
            )
        )
    ).scalar_one()
    assert row.after_state["system_accounts"] == 1


@pytest.mark.asyncio
async def test_audit_after_state_carries_system_accounts_count(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A financial instrument audit records system_accounts == 5."""
    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "KES",
            "symbol": "KSh",
            "display_name": "Kenyan Shilling",
            "account_type": "financial_wallet",
        },
    )
    assert resp.status_code == 201, resp.text
    instrument_id = resp.json()["id"]

    row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "instrument",
                AuditLog.entity_id == instrument_id,
                AuditLog.action == "instrument.created",
            )
        )
    ).scalar_one()
    assert row.after_state["system_accounts"] == 5
    # Backfill count is preserved alongside it.
    assert row.after_state["backfilled_accounts"] == 0


@pytest.mark.asyncio
async def test_provisioning_is_idempotent_when_accounts_preexist(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Pre-seeded system accounts are not duplicated by instrument create."""
    # Pre-seed the 5 money system accounts for KES (the lazy path having
    # already touched this currency before the instrument was created).
    for account_type in _FINANCIAL_SYSTEM_TYPES:
        db_session.add(
            Account(tenant_id=test_tenant.id, account_type=account_type, currency="KES")
        )
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "KES",
            "symbol": "KSh",
            "display_name": "Kenyan Shilling",
            "account_type": "financial_wallet",
        },
    )
    assert resp.status_code == 201, resp.text

    for account_type in _FINANCIAL_SYSTEM_TYPES:
        rows = await _system_accounts(db_session, str(test_tenant.id), "KES", account_type)
        assert len(rows) == 1, f"duplicate {account_type} rows for KES"


@pytest.mark.asyncio
async def test_lazy_get_or_create_returns_same_account_after_provision(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """The lazy cash-inflow helper returns the row provisioning already made."""
    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "KES",
            "symbol": "KSh",
            "display_name": "Kenyan Shilling",
            "account_type": "financial_wallet",
        },
    )
    assert resp.status_code == 201, resp.text

    provisioned = (
        await _system_accounts(
            db_session, str(test_tenant.id), "KES", ACCOUNT_TYPE_SYSTEM_CASH_INFLOW
        )
    )[0]

    # The lazy path must return the SAME account, not create a second one.
    lazy = await get_or_create_system_cash_inflow(db_session, test_tenant.id, "KES")
    assert lazy.id == provisioned.id
    rows = await _system_accounts(
        db_session, str(test_tenant.id), "KES", ACCOUNT_TYPE_SYSTEM_CASH_INFLOW
    )
    assert len(rows) == 1
