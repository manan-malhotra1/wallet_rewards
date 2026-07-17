"""Shared fixtures + helpers for money-operation maker-checker tests (Epic 18).

Provides maker / checker / second-checker auth headers with distinct Keycloak
subs (N-eyes needs distinct actors), seeding helpers for the four operations'
prerequisites, and small counters used to assert "nothing moved" on propose.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger.service import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    Account,
    Tenant,
    Transaction,
    User,
)

# Distinct Keycloak subs — N-eyes requires distinct approvers.
MAKER_SUB = "11111111-1111-4000-8000-000000000001"
CHECKER_SUB = "22222222-2222-4000-8000-000000000002"
CHECKER2_SUB = "33333333-3333-4000-8000-000000000003"


def _header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def maker_header(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """A platform-admin maker (proposes; may revise/resubmit/withdraw)."""
    return _header(make_admin_token(roles=["platform-admin"], sub=MAKER_SUB))


@pytest.fixture
def checker_header(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """A treasury-approver checker, distinct from the maker."""
    return _header(make_admin_token(roles=["treasury-approver"], sub=CHECKER_SUB))


@pytest.fixture
def checker2_header(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """A SECOND distinct treasury-approver (for six-eyes / duplicate tests)."""
    return _header(make_admin_token(roles=["treasury-approver"], sub=CHECKER2_SUB))


@pytest.fixture
def maker_who_can_approve(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """Same sub as the maker but also holds treasury-approver (self-approval test)."""
    return _header(
        make_admin_token(roles=["platform-admin", "treasury-approver"], sub=MAKER_SUB)
    )


def ops_url(tenant: Tenant, suffix: str = "") -> str:
    """Money-operations endpoint URL with the tenant_id query param."""
    return f"/api/v1/money-operations{suffix}?tenant_id={tenant.id}"


async def propose(
    client: AsyncClient,
    tenant: Tenant,
    maker_header: dict[str, str],
    operation: str,
    payload: dict,
) -> dict:
    """Propose a money operation via the API and return the response JSON."""
    resp = await client.post(
        ops_url(tenant),
        content=json.dumps({"operation": operation, "payload": payload}),
        headers=maker_header,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def approve(
    client: AsyncClient, tenant: Tenant, op_id: str, checker_header: dict[str, str]
):
    """Approve a money operation via the API."""
    return await client.post(ops_url(tenant, f"/{op_id}/approve"), headers=checker_header)


def user_phone(user: User) -> str:
    """Return the seeded phone identifier for the user fixture."""
    return next(
        ident.identifier_value for ident in user.identifiers if ident.identifier_type == "phone"
    )


async def seed_user_wallet(
    session: AsyncSession, tenant: Tenant, user: User, *, balance: Decimal = Decimal("0")
) -> Account:
    """Give the user a ZAR financial wallet, optionally pre-funded via the ledger."""
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    session.add(wallet)
    inflow = Account(
        tenant_id=tenant.id, account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW, currency="ZAR"
    )
    session.add(inflow)
    await session.commit()
    await session.refresh(wallet)
    await session.refresh(inflow)
    if balance > 0:
        await post_transaction(
            session,
            PostTransactionRequest(
                tenant_id=tenant.id,
                idempotency_key=f"bootstrap-{uuid4().hex}",
                transaction_type="bootstrap",
                currency="ZAR",
                amount=balance,
                entries=[
                    LedgerEntryRequest(account_id=inflow.id, entry_type="DEBIT", amount=balance),
                    LedgerEntryRequest(account_id=wallet.id, entry_type="CREDIT", amount=balance),
                ],
            ),
        )
        await session.commit()
    return wallet


async def seed_bank_mirror(
    session: AsyncSession, tenant: Tenant, *, name: str = "Primary", currency: str = "ZAR"
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


async def seed_system_wallet(
    session: AsyncSession, tenant: Tenant, *, currency: str = "ZAR"
) -> Account:
    """Insert a system_cash_inflow wallet — a valid adjust TARGET (not a mirror)."""
    acct = Account(
        tenant_id=tenant.id, account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW, currency=currency
    )
    session.add(acct)
    await session.commit()
    await session.refresh(acct)
    return acct


async def txn_count(session: AsyncSession, tenant: Tenant) -> int:
    """Number of transactions in the tenant (0 == nothing posted)."""
    return (
        await session.execute(
            select(func.count()).select_from(Transaction).where(Transaction.tenant_id == tenant.id)
        )
    ).scalar_one()


async def account_count(session: AsyncSession, tenant: Tenant) -> int:
    """Number of accounts in the tenant."""
    return (
        await session.execute(
            select(func.count()).select_from(Account).where(Account.tenant_id == tenant.id)
        )
    ).scalar_one()


@pytest_asyncio.fixture
async def funded_wallet(db_session: AsyncSession, test_tenant: Tenant, test_user: User) -> Account:
    """A ZAR wallet pre-loaded with 500 for withdraw tests."""
    return await seed_user_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
