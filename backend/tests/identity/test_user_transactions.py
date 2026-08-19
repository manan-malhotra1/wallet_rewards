"""Customer transaction history — an admin viewing a customer's recent transactions.

Admin-facing version of the mobile /me/wallet recent-transactions feed.
Shape matches WalletTransactionOut so the admin UI's table component
can share types with the mobile-simulator's.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger.service import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    MerchantProfile,
    Tenant,
    User,
    UserIdentifier,
    UserProfile,
)


async def _seed_wallet_with_credit(
    session: AsyncSession,
    tenant: Tenant,
    user: User,
    *,
    amount: Decimal,
    transaction_type: str = "fund",
) -> Account:
    """Give the user a ZAR wallet + post one CREDIT balanced txn."""
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    session.add(wallet)
    await session.commit()
    await session.refresh(wallet)
    # Reuse the tenant's pre-funded cash float (get-or-create) — a second
    # system_cash_inflow row would violate the unique index; its positive balance
    # absorbs the bootstrap DEBIT below (the float has a no-overdraft floor).
    from app.modules.payments.service import get_or_create_system_cash_inflow

    inflow = await get_or_create_system_cash_inflow(session, tenant.id, "ZAR")

    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=f"seed-{uuid4().hex}",
            transaction_type=transaction_type,
            currency="ZAR",
            amount=amount,
            entries=[
                LedgerEntryRequest(
                    account_id=inflow.id,
                    entry_type="DEBIT",
                    amount=amount,
                ),
                LedgerEntryRequest(
                    account_id=wallet.id,
                    entry_type="CREDIT",
                    amount=amount,
                ),
            ],
        ),
    )
    await session.commit()
    return wallet


async def _seed_named_user_with_wallet(
    session: AsyncSession,
    tenant: Tenant,
    *,
    first_name: str,
    last_name: str | None = None,
    phone: str | None = None,
    business_name: str | None = None,
    amount: Decimal,
) -> tuple[User, Account]:
    """Create a named user with a pre-funded ZAR wallet.

    Stands up the OTHER side of a user-to-user transfer so the counterparty
    name has something to resolve to. Pass `business_name` to also give the
    user a merchant profile — that name must WIN over the person name.
    """
    user = User(tenant_id=tenant.id)
    session.add(user)
    await session.flush()
    session.add(UserProfile(user_id=user.id, first_name=first_name, last_name=last_name))
    if phone is not None:
        session.add(
            UserIdentifier(
                user_id=user.id,
                tenant_id=tenant.id,
                identifier_type="phone",
                identifier_value=phone,
                verified=True,
            )
        )
    if business_name is not None:
        session.add(
            MerchantProfile(
                tenant_id=tenant.id,
                user_id=user.id,
                business_name=business_name,
                category="airtime",
                service_code=f"svc_{uuid4().hex[:8]}",
            )
        )
    await session.commit()
    wallet = await _seed_wallet_with_credit(session, tenant, user, amount=amount)
    return user, wallet


async def _post_user_to_user_txn(
    session: AsyncSession,
    tenant: Tenant,
    *,
    payer_wallet: Account,
    payee_wallet: Account,
    transaction_type: str,
    amount: Decimal,
) -> None:
    """Post a balanced DEBIT-payer / CREDIT-payee transaction of any type."""
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=f"{transaction_type}-{uuid4().hex}",
            transaction_type=transaction_type,
            currency="ZAR",
            amount=amount,
            entries=[
                LedgerEntryRequest(account_id=payer_wallet.id, entry_type="DEBIT", amount=amount),
                LedgerEntryRequest(account_id=payee_wallet.id, entry_type="CREDIT", amount=amount),
            ],
        ),
    )
    await session.commit()


@pytest.mark.asyncio
async def test_user_transactions_requires_auth(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify viewing a customer's transactions requires signing in"""
    resp = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}/transactions",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_user_transactions_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can see a customer's recent transactions"""
    await _seed_wallet_with_credit(db_session, test_tenant, test_user, amount=Decimal("500"))

    resp = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}/transactions",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["transaction_type"] == "fund"
    assert row["direction"] == "in"
    assert Decimal(row["amount"]) == Decimal("500")
    assert row["currency"] == "ZAR"


@pytest.mark.asyncio
async def test_merchant_cashin_shows_the_merchants_business_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a customer funded by a merchant sees the merchant's business name

    A merchant is a user, so it also carries a person name — but an operator
    looking at a cash-in needs the TRADING name, so the business name wins.
    """
    consumer_wallet = await _seed_wallet_with_credit(
        db_session, test_tenant, test_user, amount=Decimal("100")
    )
    _, merchant_wallet = await _seed_named_user_with_wallet(
        db_session,
        test_tenant,
        first_name="Cash-in",
        last_name="Merchant",
        business_name="Acme Airtime",
        amount=Decimal("500"),
    )
    await _post_user_to_user_txn(
        db_session,
        test_tenant,
        payer_wallet=merchant_wallet,
        payee_wallet=consumer_wallet,
        transaction_type="merchant_cashin",
        amount=Decimal("200"),
    )

    resp = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}/transactions",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    cashin = next(r for r in rows if r["transaction_type"] == "merchant_cashin")
    assert cashin["direction"] == "in"
    assert cashin["counterparty_name"] == "Acme Airtime"


@pytest.mark.asyncio
async def test_counterparty_phone_is_returned_for_admins(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin sees the counterparty's phone number alongside the name"""
    consumer_wallet = await _seed_wallet_with_credit(
        db_session, test_tenant, test_user, amount=Decimal("100")
    )
    _, agent_wallet = await _seed_named_user_with_wallet(
        db_session,
        test_tenant,
        first_name="Grace",
        last_name="Dube",
        phone="+27825550142",
        amount=Decimal("500"),
    )
    await _post_user_to_user_txn(
        db_session,
        test_tenant,
        payer_wallet=agent_wallet,
        payee_wallet=consumer_wallet,
        transaction_type="cash_in",
        amount=Decimal("200"),
    )

    resp = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}/transactions",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    cashin = next(r for r in resp.json() if r["transaction_type"] == "cash_in")
    # Full person name for an agent (no business name to prefer).
    assert cashin["counterparty_name"] == "Grace Dube"
    assert cashin["counterparty_phone"] == "+27825550142"


@pytest.mark.asyncio
async def test_system_funded_transaction_has_no_counterparty_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a system-funded transaction shows no counterparty name"""
    await _seed_wallet_with_credit(db_session, test_tenant, test_user, amount=Decimal("100"))

    resp = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}/transactions",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows[0]["transaction_type"] == "fund"
    # The other leg is the system cash float (user_id IS NULL) — nothing to name.
    assert rows[0]["counterparty_name"] is None


@pytest.mark.asyncio
async def test_user_transactions_unknown_user_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify viewing transactions for a customer who does not exist is rejected"""
    resp = await async_client.get(
        f"/api/v1/identity/users/{uuid4()}/transactions",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_user_transactions_cross_tenant_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin cannot see the transactions of a customer in another tenant"""
    await _seed_wallet_with_credit(db_session, test_tenant, test_user, amount=Decimal("100"))

    resp = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}/transactions",
        params={"tenant_id": str(other_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_user_transactions_limit_bounds_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify out-of-bounds limits are rejected with 422 instead of honoured.

    Previously `limit` was an unvalidated plain default, so a caller could
    request the user's entire 7-year transaction history in one response.
    """
    for limit in (0, -5, 100000):
        resp = await async_client.get(
            f"/api/v1/identity/users/{test_user.id}/transactions",
            params={"tenant_id": str(test_tenant.id), "limit": limit},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, limit
