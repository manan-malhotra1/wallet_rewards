"""Tests for POST /api/v1/treasury/withdraw (admin pull-back).

Mirrors test_fund_user.py but verifies the reverse direction (user wallet
debited, operator_adjustment credited). Admin operations are PIN-less and
fee-less — step-up PIN policies apply to user-initiated transactions
only, not back-office moves.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
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
    User,
)


def _user_phone(user: User) -> str:
    """Return the seeded phone identifier for the user fixture."""
    return next(
        ident.identifier_value for ident in user.identifiers if ident.identifier_type == "phone"
    )


async def _seed_user_wallet_with_balance(
    session: AsyncSession,
    tenant: Tenant,
    user: User,
    *,
    starting_balance: Decimal,
) -> Account:
    """Give the user a ZAR wallet seeded with `starting_balance`."""
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    session.add(wallet)
    inflow = Account(
        tenant_id=tenant.id,
        account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
        currency="ZAR",
    )
    session.add(inflow)
    await session.commit()
    await session.refresh(wallet)
    await session.refresh(inflow)

    # Bootstrap the balance via a manually-posted balanced transaction —
    # avoids the higher-level top_up code path so the test stays focused.
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=f"bootstrap-{uuid4().hex}",
            transaction_type="bootstrap",
            currency="ZAR",
            amount=starting_balance,
            entries=[
                LedgerEntryRequest(
                    account_id=inflow.id,
                    entry_type="DEBIT",
                    amount=starting_balance,
                ),
                LedgerEntryRequest(
                    account_id=wallet.id,
                    entry_type="CREDIT",
                    amount=starting_balance,
                ),
            ],
        ),
    )
    await session.commit()
    return wallet


@pytest.mark.asyncio
async def test_withdraw_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Withdraw 200 from a 500-balance wallet → new balance 300."""
    wallet = await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )

    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "200",
            "currency": "ZAR",
            "reason": "Cash-out at agent counter.",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(body["new_balance"]) == Decimal("300")

    # Direct ledger check: user wallet now sits at 300.
    new_balance, _ = await derive_balance(db_session, wallet.id)
    assert new_balance == Decimal("300")


@pytest.mark.asyncio
async def test_withdraw_credits_operator_adjustment(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Counter-leg lands on the operator_adjustment account (lazy-created)."""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )

    await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "120",
            "currency": "ZAR",
            "reason": "Counter cash-out.",
        },
    )

    operator_account = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == test_tenant.id,
                Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
                Account.currency == "ZAR",
            )
        )
    ).scalar_one()
    op_balance, _ = await derive_balance(db_session, operator_account.id)
    assert op_balance == Decimal("120")


@pytest.mark.asyncio
async def test_withdraw_rejects_insufficient_balance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Pulling more than the wallet holds → 409 insufficient_funds."""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("50")
    )

    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "100",
            "currency": "ZAR",
            "reason": "Over-draw attempt.",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "insufficient_funds"


@pytest.mark.asyncio
async def test_withdraw_missing_wallet_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """User without a wallet for the currency → 404."""
    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "10",
            "currency": "ZAR",
            "reason": "No wallet.",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_withdraw_requires_auth(
    async_client: AsyncClient, test_tenant: Tenant, test_user: User
) -> None:
    """Anonymous withdraw → 401."""
    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "10",
            "currency": "ZAR",
            "reason": "x",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_withdraw_ignores_user_pin_field(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Admin treasury endpoints are PIN-less — an unknown 'pin' field is
    rejected at validation rather than silently consumed."""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )
    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "100",
            "currency": "ZAR",
            "reason": "smoke test",
            # Stray PIN field — Pydantic default ignores extras, so this
            # asserts the *backend* does not act on it. The withdraw
            # still completes 201.
            "pin": "1234",
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_withdraw_cross_tenant_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """User in tenant A, withdraw scoped to tenant B → 404."""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("100")
    )

    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(other_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "10",
            "currency": "ZAR",
            "reason": "wrong tenant",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_withdraw_all_empties_the_wallet(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """withdraw_all with no amount pulls the full available balance (E18-S1)."""
    wallet = await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )
    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "withdraw_all": True,
            "currency": "ZAR",
            "reason": "Close account — withdraw all.",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(body["amount"]) == Decimal("500")
    assert Decimal(body["new_balance"]) == Decimal("0")
    new_balance, _ = await derive_balance(db_session, wallet.id)
    assert new_balance == Decimal("0")


@pytest.mark.asyncio
async def test_withdraw_all_with_amount_is_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Sending both amount and withdraw_all is a validation error."""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("100")
    )
    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "10",
            "withdraw_all": True,
            "currency": "ZAR",
            "reason": "conflicting",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_withdraw_without_amount_or_all_is_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Neither amount nor withdraw_all → validation error."""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("100")
    )
    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "currency": "ZAR",
            "reason": "no amount",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_withdraw_all_on_empty_wallet_is_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """withdraw_all on a zero-balance wallet → 409 nothing_to_withdraw."""
    wallet = Account(
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    db_session.add(wallet)
    await db_session.commit()

    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "withdraw_all": True,
            "currency": "ZAR",
            "reason": "nothing there",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "nothing_to_withdraw"
