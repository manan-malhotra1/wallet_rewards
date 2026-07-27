"""Pulling funds back from a customer.

Epic 18: withdraw now PROPOSES a money operation; the debit posts only after a
distinct treasury-approver approves it. Body-level validation (amount/withdraw_all
xor, required bank mirror, auth) still fails at propose time. Resolution failures
(unknown/foreign/mismatched mirror, missing wallet, insufficient funds, nothing to
withdraw) surface at APPLY time — i.e. on the approve call.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
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
    Account,
    Tenant,
    User,
)
from tests.treasury.conftest import approve_op


def _user_phone(user: User) -> str:
    """Return the seeded phone identifier for the user fixture."""
    return next(
        ident.identifier_value for ident in user.identifiers if ident.identifier_type == "phone"
    )


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
    await session.commit()
    await session.refresh(wallet)
    # Reuse the tenant's pre-funded cash float (get-or-create) rather than
    # constructing a second system_cash_inflow row (would violate the unique
    # index) — its positive balance absorbs the bootstrap DEBIT below.
    from app.modules.payments.service import get_or_create_system_cash_inflow

    inflow = await get_or_create_system_cash_inflow(session, tenant.id, "ZAR")

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
                    account_id=inflow.id, entry_type="DEBIT", amount=starting_balance
                ),
                LedgerEntryRequest(
                    account_id=wallet.id, entry_type="CREDIT", amount=starting_balance
                ),
            ],
        ),
    )
    await session.commit()
    return wallet


async def _propose_withdraw(
    client: AsyncClient, tenant: Tenant, user: User, admin_auth_header: dict[str, str], **overrides
):
    """Propose a withdraw via the treasury endpoint; return the HTTP response."""
    body = {
        "tenant_id": str(tenant.id),
        "identifier_type": "phone",
        "identifier_value": _user_phone(user),
        "currency": "ZAR",
        "reason": "cash-out",
    }
    body.update(overrides)
    return await client.post("/api/v1/treasury/withdraw", headers=admin_auth_header, json=body)


@pytest.mark.asyncio
async def test_withdraw_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify an admin can pull funds from a customer's wallet once a second admin approves it"""
    wallet = await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )
    mirror = await _seed_bank_mirror(db_session, test_tenant)

    proposed = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        amount="200",
        bank_mirror_account_id=str(mirror.id),
    )
    assert proposed.status_code == 201, proposed.text
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 200, approved.text

    new_balance, _ = await derive_balance(db_session, wallet.id)
    assert new_balance == Decimal("300")


@pytest.mark.asyncio
async def test_withdraw_credits_chosen_bank_mirror(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify a pulled-back amount lands on the bank record the operator chose"""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )
    chosen = await _seed_bank_mirror(db_session, test_tenant, name="Standard Bank")
    other = await _seed_bank_mirror(db_session, test_tenant, name="Nedbank")

    proposed = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        amount="120",
        bank_mirror_account_id=str(chosen.id),
    )
    await approve_op(async_client, str(test_tenant.id), proposed.json()["id"], approver_header)

    chosen_balance, _ = await derive_balance(db_session, chosen.id)
    other_balance, _ = await derive_balance(db_session, other.id)
    assert chosen_balance == Decimal("120")
    assert other_balance == Decimal("0")


@pytest.mark.asyncio
async def test_withdraw_unknown_mirror_returns_404_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify pulling funds against a bank record that does not exist is refused"""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )
    proposed = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        amount="100",
        bank_mirror_account_id=str(uuid4()),
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 404


@pytest.mark.asyncio
async def test_withdraw_foreign_tenant_mirror_returns_404_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify pulling funds against another tenant's bank record is refused"""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )
    foreign_mirror = await _seed_bank_mirror(db_session, other_tenant)
    proposed = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        amount="100",
        bank_mirror_account_id=str(foreign_mirror.id),
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 404


@pytest.mark.asyncio
async def test_withdraw_mirror_currency_mismatch_returns_422_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify pulling funds must use a bank record in the same currency"""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )
    usd_mirror = await _seed_bank_mirror(db_session, test_tenant, name="USD Mirror", currency="USD")
    proposed = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        amount="100",
        bank_mirror_account_id=str(usd_mirror.id),
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 422
    assert approved.json()["error_code"] == "currency_mismatch"


@pytest.mark.asyncio
async def test_withdraw_rejects_insufficient_balance_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify an admin cannot pull back more than a customer's wallet holds"""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("50")
    )
    mirror = await _seed_bank_mirror(db_session, test_tenant)
    proposed = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        amount="100",
        bank_mirror_account_id=str(mirror.id),
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 409
    assert approved.json()["error_code"] == "insufficient_funds"


@pytest.mark.asyncio
async def test_withdraw_missing_wallet_returns_404_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify pulling funds from a customer with no wallet in that currency is refused"""
    mirror = await _seed_bank_mirror(db_session, test_tenant)
    proposed = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        amount="10",
        bank_mirror_account_id=str(mirror.id),
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 404


@pytest.mark.asyncio
async def test_withdraw_requires_auth(
    async_client: AsyncClient, test_tenant: Tenant, test_user: User
) -> None:
    """Verify an unauthenticated user cannot pull funds from a customer"""
    resp = await async_client.post(
        "/api/v1/treasury/withdraw",
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "10",
            "currency": "ZAR",
            "bank_mirror_account_id": str(uuid4()),
            "reason": "x",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_withdraw_missing_bank_mirror_is_validation_error(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify pulling funds must name which bank record to use"""
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
            "currency": "ZAR",
            "reason": "no mirror supplied",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_withdraw_ignores_user_pin_field(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify a stray PIN field does not affect an admin fund pull-back"""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )
    mirror = await _seed_bank_mirror(db_session, test_tenant)
    proposed = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        amount="100",
        bank_mirror_account_id=str(mirror.id),
        pin="1234",
    )
    assert proposed.status_code == 201, proposed.text
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 200, approved.text


@pytest.mark.asyncio
async def test_withdraw_cross_tenant_returns_404_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify an admin cannot pull funds from a customer in another tenant

    User in tenant A, withdraw scoped to tenant B → 404 on approval.

    The proposal is created under tenant B (which exists); the user can't be
    resolved there, so the failure surfaces when the operation executes.
    """
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("100")
    )
    mirror = await _seed_bank_mirror(db_session, other_tenant)
    proposed = await _propose_withdraw(
        async_client,
        other_tenant,
        test_user,
        admin_auth_header,
        amount="10",
        bank_mirror_account_id=str(mirror.id),
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(other_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 404


@pytest.mark.asyncio
async def test_withdraw_all_empties_the_wallet(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify pulling back everything empties a customer's wallet"""
    wallet = await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("500")
    )
    mirror = await _seed_bank_mirror(db_session, test_tenant)
    proposed = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        withdraw_all=True,
        bank_mirror_account_id=str(mirror.id),
    )
    assert proposed.status_code == 201, proposed.text
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 200, approved.text
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
    """Verify an admin cannot ask to pull back everything and a fixed amount at once"""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("100")
    )
    resp = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        amount="10",
        withdraw_all=True,
        bank_mirror_account_id=str(uuid4()),
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
    """Verify an admin must say how much to pull back"""
    await _seed_user_wallet_with_balance(
        db_session, test_tenant, test_user, starting_balance=Decimal("100")
    )
    resp = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        bank_mirror_account_id=str(uuid4()),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_withdraw_all_on_empty_wallet_is_rejected_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify pulling back everything from an empty wallet is refused"""
    wallet = Account(
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    db_session.add(wallet)
    await db_session.commit()
    mirror = await _seed_bank_mirror(db_session, test_tenant)

    proposed = await _propose_withdraw(
        async_client,
        test_tenant,
        test_user,
        admin_auth_header,
        withdraw_all=True,
        bank_mirror_account_id=str(mirror.id),
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 409
    assert approved.json()["error_code"] == "nothing_to_withdraw"
