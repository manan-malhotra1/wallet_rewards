"""Tests for POST /api/v1/treasury/adjust-system-wallet (fund/withdraw float).

Every adjust now requires an explicit `bank_mirror_account_id` — the operator
picks which bank mirror (operator_adjustment) is the counter-leg (Epic 26).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.shared.models import (
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    Account,
    Tenant,
)


async def _seed_system_cash_inflow(
    session: AsyncSession, tenant: Tenant, currency: str = "ZAR"
) -> Account:
    """Insert a system_cash_inflow account for the tenant."""
    acct = Account(
        tenant_id=tenant.id,
        user_id=None,
        account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
        currency=currency,
    )
    session.add(acct)
    await session.commit()
    await session.refresh(acct)
    return acct


async def _seed_bank_mirror(
    session: AsyncSession,
    tenant: Tenant,
    *,
    name: str = "Primary",
    currency: str = "ZAR",
) -> Account:
    """Insert a named bank mirror (operator_adjustment) for the tenant."""
    mirror = Account(
        tenant_id=tenant.id,
        user_id=None,
        account_type=ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        currency=currency,
        name=name,
    )
    session.add(mirror)
    await session.commit()
    await session.refresh(mirror)
    return mirror


@pytest.mark.asyncio
async def test_fund_float_credits_target_and_debits_chosen_mirror(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Positive amount: target balance goes up, the chosen mirror goes down."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    mirror = await _seed_bank_mirror(db_session, test_tenant)

    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "1000000",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "Initial R 1M float wire from Standard Bank.",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(body["amount"]) == Decimal("1000000")
    assert Decimal(body["new_balance"]) == Decimal("1000000")

    # The chosen mirror should now show -1,000,000.
    mirror_balance, _ = await derive_balance(db_session, mirror.id)
    assert mirror_balance == Decimal("-1000000")


@pytest.mark.asyncio
async def test_adjust_posts_counter_leg_to_the_chosen_mirror(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """The counter-leg lands on the selected mirror, leaving others untouched."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    chosen = await _seed_bank_mirror(db_session, test_tenant, name="Standard Bank")
    other = await _seed_bank_mirror(db_session, test_tenant, name="Nedbank")

    await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "5000",
            "bank_mirror_account_id": str(chosen.id),
            "reason": "Top-up via Standard Bank wire.",
        },
    )

    chosen_balance, _ = await derive_balance(db_session, chosen.id)
    other_balance, _ = await derive_balance(db_session, other.id)
    assert chosen_balance == Decimal("-5000")
    assert other_balance == Decimal("0")


@pytest.mark.asyncio
async def test_withdraw_float_debits_target_and_credits_mirror(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Negative amount: target goes down, the chosen mirror goes up."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    mirror = await _seed_bank_mirror(db_session, test_tenant)

    # First fund R 500K.
    await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "500000",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "seed fund",
        },
    )
    # Now withdraw R 100K.
    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "-100000",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "Ops expense — server bill.",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(body["new_balance"]) == Decimal("400000")


@pytest.mark.asyncio
async def test_adjust_zero_amount_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Zero adjustment is meaningless → 422."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    mirror = await _seed_bank_mirror(db_session, test_tenant)

    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "0",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "no-op",
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "amount_zero"


@pytest.mark.asyncio
async def test_adjust_cross_tenant_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Adjusting another tenant's account must return 404."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    mirror = await _seed_bank_mirror(db_session, other_tenant)
    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(other_tenant.id),
            "account_id": str(target.id),
            "amount": "1000",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "cross-tenant attempt",
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_adjust_bank_mirror_as_target(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A bank mirror is only ever a counter-leg; targeting one rejects 422."""
    target_mirror = await _seed_bank_mirror(db_session, test_tenant, name="Target")
    counter_mirror = await _seed_bank_mirror(db_session, test_tenant, name="Counter")

    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target_mirror.id),
            "amount": "1000",
            "bank_mirror_account_id": str(counter_mirror.id),
            "reason": "shouldnt work",
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "cannot_adjust_operator_adjustment"


@pytest.mark.asyncio
async def test_adjust_unknown_account_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Unknown account_id → 404."""
    mirror = await _seed_bank_mirror(db_session, test_tenant)
    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(uuid4()),
            "amount": "1000",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "test",
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_adjust_unknown_mirror_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A bank_mirror_account_id that doesn't exist → 404."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "1000",
            "bank_mirror_account_id": str(uuid4()),
            "reason": "bad mirror",
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_adjust_mirror_currency_mismatch_returns_422(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A mirror in a different currency than the target → 422."""
    target = await _seed_system_cash_inflow(db_session, test_tenant, currency="ZAR")
    usd_mirror = await _seed_bank_mirror(db_session, test_tenant, name="USD", currency="USD")
    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "1000",
            "bank_mirror_account_id": str(usd_mirror.id),
            "reason": "currency mismatch",
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "currency_mismatch"


@pytest.mark.asyncio
async def test_adjust_requires_auth(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Anonymous adjust → 401."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    mirror = await _seed_bank_mirror(db_session, test_tenant)
    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "1000",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "no auth",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_adjust_missing_bank_mirror_is_validation_error(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Omitting bank_mirror_account_id is a 422 — the field is now required."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "1000",
            "reason": "no mirror",
        },
    )
    assert response.status_code == 422
