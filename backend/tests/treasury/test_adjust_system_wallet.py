"""Adjusting the operator float.

Epic 18: adjust now PROPOSES a money operation; the transaction posts only after
a distinct treasury-approver approves it. Body-level validation (required bank
mirror, auth) and payload validation (non-zero amount) fail at propose time.
Target/mirror resolution failures surface at APPLY time — on the approve call.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.shared.models import (
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    Account,
    Tenant,
)
from tests.treasury.conftest import approve_op


@pytest_asyncio.fixture
async def test_tenant(db_session: AsyncSession) -> Tenant:
    """Un-prefunded tenant (no cash-float top-up) so these tests can create the
    float target themselves and assert its EXACT post-adjust balance.

    Shadows the conftest `test_tenant` (which pre-funds the ZAR float) for this
    module only — the pre-fund would both collide with `_seed_system_cash_inflow`
    (unique float row) and skew the target's balance assertions.
    """
    tenant = Tenant(name=f"adjust-{uuid4().hex[:8]}", business_type="both", base_currency="ZAR")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


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


async def _propose_adjust(
    client: AsyncClient,
    tenant: Tenant,
    admin_auth_header: dict[str, str],
    *,
    account_id: str,
    amount: str,
    bank_mirror_account_id: str,
    reason: str = "adjust",
):
    """Propose an adjust via the treasury endpoint; return the HTTP response."""
    return await client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(tenant.id),
            "account_id": account_id,
            "amount": amount,
            "bank_mirror_account_id": bank_mirror_account_id,
            "reason": reason,
        },
    )


@pytest.mark.asyncio
async def test_fund_float_credits_target_and_debits_chosen_mirror(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify topping up the operator float raises it and lowers the chosen bank record"""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    mirror = await _seed_bank_mirror(db_session, test_tenant)

    proposed = await _propose_adjust(
        async_client,
        test_tenant,
        admin_auth_header,
        account_id=str(target.id),
        amount="1000000",
        bank_mirror_account_id=str(mirror.id),
        reason="Initial R 1M float wire from Standard Bank.",
    )
    assert proposed.status_code == 201, proposed.text
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 200, approved.text

    target_balance, _ = await derive_balance(db_session, target.id)
    mirror_balance, _ = await derive_balance(db_session, mirror.id)
    assert target_balance == Decimal("1000000")
    assert mirror_balance == Decimal("-1000000")


@pytest.mark.asyncio
async def test_adjust_posts_counter_leg_to_the_chosen_mirror(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify a float adjustment affects only the bank record the operator chose"""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    chosen = await _seed_bank_mirror(db_session, test_tenant, name="Standard Bank")
    other = await _seed_bank_mirror(db_session, test_tenant, name="Nedbank")

    proposed = await _propose_adjust(
        async_client,
        test_tenant,
        admin_auth_header,
        account_id=str(target.id),
        amount="5000",
        bank_mirror_account_id=str(chosen.id),
    )
    await approve_op(async_client, str(test_tenant.id), proposed.json()["id"], approver_header)

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
    approver_header: dict[str, str],
) -> None:
    """Verify drawing down the operator float lowers it and raises the chosen bank record"""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    mirror = await _seed_bank_mirror(db_session, test_tenant)

    fund = await _propose_adjust(
        async_client,
        test_tenant,
        admin_auth_header,
        account_id=str(target.id),
        amount="500000",
        bank_mirror_account_id=str(mirror.id),
        reason="seed fund",
    )
    await approve_op(async_client, str(test_tenant.id), fund.json()["id"], approver_header)

    withdraw = await _propose_adjust(
        async_client,
        test_tenant,
        admin_auth_header,
        account_id=str(target.id),
        amount="-100000",
        bank_mirror_account_id=str(mirror.id),
        reason="Ops expense — server bill.",
    )
    approved = await approve_op(
        async_client, str(test_tenant.id), withdraw.json()["id"], approver_header
    )
    assert approved.status_code == 200, approved.text

    target_balance, _ = await derive_balance(db_session, target.id)
    assert target_balance == Decimal("400000")


@pytest.mark.asyncio
async def test_adjust_zero_amount_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an operator cannot make a float adjustment of zero"""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    mirror = await _seed_bank_mirror(db_session, test_tenant)

    response = await _propose_adjust(
        async_client,
        test_tenant,
        admin_auth_header,
        account_id=str(target.id),
        amount="0",
        bank_mirror_account_id=str(mirror.id),
        reason="no-op",
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "money_operation_invalid_payload"


@pytest.mark.asyncio
async def test_adjust_cross_tenant_returns_404_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify an operator cannot adjust another tenant's float"""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    mirror = await _seed_bank_mirror(db_session, other_tenant)
    proposed = await _propose_adjust(
        async_client,
        other_tenant,
        admin_auth_header,
        account_id=str(target.id),
        amount="1000",
        bank_mirror_account_id=str(mirror.id),
        reason="cross-tenant attempt",
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(other_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 404


@pytest.mark.asyncio
async def test_cannot_adjust_bank_mirror_as_target_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify a bank record cannot itself be the target of a float adjustment"""
    target_mirror = await _seed_bank_mirror(db_session, test_tenant, name="Target")
    counter_mirror = await _seed_bank_mirror(db_session, test_tenant, name="Counter")

    proposed = await _propose_adjust(
        async_client,
        test_tenant,
        admin_auth_header,
        account_id=str(target_mirror.id),
        amount="1000",
        bank_mirror_account_id=str(counter_mirror.id),
        reason="shouldnt work",
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 422
    assert approved.json()["error_code"] == "cannot_adjust_operator_adjustment"


@pytest.mark.asyncio
async def test_adjust_unknown_account_returns_404_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify adjusting an account that does not exist is refused"""
    mirror = await _seed_bank_mirror(db_session, test_tenant)
    proposed = await _propose_adjust(
        async_client,
        test_tenant,
        admin_auth_header,
        account_id=str(uuid4()),
        amount="1000",
        bank_mirror_account_id=str(mirror.id),
        reason="test",
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 404


@pytest.mark.asyncio
async def test_adjust_unknown_mirror_returns_404_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify adjusting the float against a bank record that does not exist is refused"""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    proposed = await _propose_adjust(
        async_client,
        test_tenant,
        admin_auth_header,
        account_id=str(target.id),
        amount="1000",
        bank_mirror_account_id=str(uuid4()),
        reason="bad mirror",
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 404


@pytest.mark.asyncio
async def test_adjust_mirror_currency_mismatch_returns_422_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify a float adjustment must use a bank record in the same currency"""
    target = await _seed_system_cash_inflow(db_session, test_tenant, currency="ZAR")
    usd_mirror = await _seed_bank_mirror(db_session, test_tenant, name="USD", currency="USD")
    proposed = await _propose_adjust(
        async_client,
        test_tenant,
        admin_auth_header,
        account_id=str(target.id),
        amount="1000",
        bank_mirror_account_id=str(usd_mirror.id),
        reason="currency mismatch",
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 422
    assert approved.json()["error_code"] == "currency_mismatch"


@pytest.mark.asyncio
async def test_adjust_requires_auth(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Verify an unauthenticated user cannot adjust the operator float"""
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
    """Verify a float adjustment must name which bank record to use"""
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
