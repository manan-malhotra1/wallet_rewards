"""The treasury money-moving endpoints now PROPOSE a money operation (Epic 18).

POST /treasury/{fund-user,withdraw,adjust-system-wallet,bank-mirrors} return a
PENDING money-operation request and execute nothing until a distinct checker
approves it via /money-operations. rename_bank_mirror stays a direct op (tested
elsewhere).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.shared.models import Tenant, User
from tests.money_operations.conftest import (
    approve,
    seed_float,
    seed_user_wallet,
    txn_count,
    user_phone,
)


@pytest.mark.asyncio
async def test_treasury_fund_user_proposes_not_executes(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
) -> None:
    """POST /treasury/fund-user returns a PENDING money operation; no money moved."""
    wallet = await seed_user_wallet(db_session, test_tenant, test_user)
    resp = await async_client.post(
        "/api/v1/treasury/fund-user",
        headers=maker_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": user_phone(test_user),
            "amount": "500",
            "currency": "ZAR",
            "reason": "Onboarding gift.",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "PENDING"
    assert body["operation"] == "fund_user"

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("0")
    assert await txn_count(db_session, test_tenant) == 0


@pytest.mark.asyncio
async def test_treasury_fund_user_executes_after_approval(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """The proposal created via the treasury endpoint applies once approved."""
    wallet = await seed_user_wallet(db_session, test_tenant, test_user)
    # The approved fund_user DEBITs the cash float; pre-fund it (no-overdraft floor).
    await seed_float(db_session, test_tenant, Decimal("1000"))
    proposed = await async_client.post(
        "/api/v1/treasury/fund-user",
        headers=maker_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": user_phone(test_user),
            "amount": "500",
            "currency": "ZAR",
            "reason": "Onboarding gift.",
        },
    )
    op_id = proposed.json()["id"]
    approved = await approve(async_client, test_tenant, op_id, checker_header)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPLIED"

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("500")


@pytest.mark.asyncio
async def test_treasury_bank_mirror_proposes_not_executes(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """POST /treasury/bank-mirrors proposes; the account isn't created yet."""
    from tests.money_operations.conftest import account_count

    before = await account_count(db_session, test_tenant)
    resp = await async_client.post(
        f"/api/v1/treasury/bank-mirrors?tenant_id={test_tenant.id}",
        headers=maker_header,
        json={"currency": "ZAR", "name": "Nedbank"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "PENDING"
    assert resp.json()["operation"] == "create_bank_mirror"
    assert await account_count(db_session, test_tenant) == before


@pytest.mark.asyncio
async def test_treasury_fund_user_requires_auth(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Anonymous propose via the treasury endpoint → 401."""
    resp = await async_client.post(
        "/api/v1/treasury/fund-user",
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": user_phone(test_user),
            "amount": "10",
            "currency": "ZAR",
            "reason": "x",
        },
    )
    assert resp.status_code == 401
