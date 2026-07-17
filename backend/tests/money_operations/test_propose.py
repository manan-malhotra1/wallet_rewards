"""Propose each of the four money operations → PENDING, NOTHING executed.

A proposal records the request + a `submitted` review, resolves
required_approvals, and moves no money / creates no account until approved.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Account, Tenant, User
from tests.money_operations.conftest import (
    account_count,
    ops_url,
    propose,
    seed_bank_mirror,
    seed_system_wallet,
    seed_user_wallet,
    txn_count,
    user_phone,
)


@pytest.mark.asyncio
async def test_propose_fund_user_is_pending_no_money_moved(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
) -> None:
    """fund_user propose → PENDING, no transaction posted."""
    await seed_user_wallet(db_session, test_tenant, test_user)
    body = await propose(
        async_client,
        test_tenant,
        maker_header,
        "fund_user",
        {
            "identifier_type": "phone",
            "identifier_value": user_phone(test_user),
            "amount": "100",
            "currency": "ZAR",
            "reason": "gift",
        },
    )
    assert body["status"] == "PENDING"
    assert body["operation"] == "fund_user"
    assert body["required_approvals"] == 1
    assert body["approvals_count"] == 0
    assert body["applied_transaction_id"] is None
    assert [r["action"] for r in body["reviews"]] == ["submitted"]
    assert await txn_count(db_session, test_tenant) == 0


@pytest.mark.asyncio
async def test_propose_withdraw_user_is_pending_no_money_moved(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    funded_wallet: Account,
    maker_header: dict[str, str],
) -> None:
    """withdraw_user propose → PENDING; the 500 balance is untouched."""
    mirror = await seed_bank_mirror(db_session, test_tenant)
    body = await propose(
        async_client,
        test_tenant,
        maker_header,
        "withdraw_user",
        {
            "identifier_type": "phone",
            "identifier_value": user_phone(test_user),
            "amount": "200",
            "currency": "ZAR",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "cash-out",
        },
    )
    assert body["status"] == "PENDING"
    # Only the bootstrap that funded the wallet exists — no withdraw posted.
    assert await txn_count(db_session, test_tenant) == 1


@pytest.mark.asyncio
async def test_propose_adjust_system_wallet_is_pending(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """adjust_system_wallet propose → PENDING, no transaction posted."""
    target = await seed_system_wallet(db_session, test_tenant)
    mirror = await seed_bank_mirror(db_session, test_tenant)
    body = await propose(
        async_client,
        test_tenant,
        maker_header,
        "adjust_system_wallet",
        {
            "account_id": str(target.id),
            "amount": "300",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "float top-up",
        },
    )
    assert body["status"] == "PENDING"
    assert await txn_count(db_session, test_tenant) == 0


@pytest.mark.asyncio
async def test_propose_create_bank_mirror_is_pending_no_account(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """create_bank_mirror propose → PENDING, NO account created yet."""
    before = await account_count(db_session, test_tenant)
    body = await propose(
        async_client,
        test_tenant,
        maker_header,
        "create_bank_mirror",
        {"currency": "ZAR", "name": "Standard Bank"},
    )
    assert body["status"] == "PENDING"
    assert await account_count(db_session, test_tenant) == before


@pytest.mark.asyncio
async def test_propose_invalid_payload_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """A payload failing the operation schema (negative amount) → 422."""
    resp = await async_client.post(
        ops_url(test_tenant),
        content=json.dumps(
            {
                "operation": "fund_user",
                "payload": {
                    "identifier_type": "phone",
                    "identifier_value": "+27 82 555 0000",
                    "amount": "-5",
                    "currency": "ZAR",
                },
            }
        ),
        headers=maker_header,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_propose_unknown_operation_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """An unrecognised operation → 422."""
    resp = await async_client.post(
        ops_url(test_tenant),
        content=json.dumps({"operation": "delete_everything", "payload": {}}),
        headers=maker_header,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_propose_requires_platform_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    checker_header: dict[str, str],
) -> None:
    """A treasury-approver (no platform-admin) cannot propose → 403."""
    resp = await async_client.post(
        ops_url(test_tenant),
        content=json.dumps(
            {"operation": "create_bank_mirror", "payload": {"currency": "ZAR", "name": "X"}}
        ),
        headers=checker_header,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_propose_unknown_tenant_404(
    async_client: AsyncClient,
    maker_header: dict[str, str],
) -> None:
    """Proposing against an unknown tenant → 404."""
    from uuid import uuid4

    resp = await async_client.post(
        f"/api/v1/money-operations?tenant_id={uuid4()}",
        content=json.dumps(
            {"operation": "create_bank_mirror", "payload": {"currency": "ZAR", "name": "X"}}
        ),
        headers=maker_header,
    )
    assert resp.status_code == 404
