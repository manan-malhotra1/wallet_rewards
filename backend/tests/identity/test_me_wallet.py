"""My wallet — the account view a signed-in customer sees.

The mobile-simulator and the eventual real mobile app call this endpoint
to render the user's accounts + recent transactions. Auth is the user's
session token (PIN login), NOT admin.

Covers:
  - Happy path: authenticated user gets their own accounts + recent txns
  - 401: no Authorization header
  - 401: bad / expired token
  - No data leak: a second user's accounts never appear in the response
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    Account,
    Tenant,
    User,
    UserIdentifier,
)
from tests.conftest import create_session_token_for_user


async def _seed_p2p_fee_config(session: AsyncSession, tenant_id) -> None:
    """Seed a p2p pricing (fixed fee) + limit config so a fee-bearing p2p runs.

    Invariant #12 makes the pricing+limit gate unconditional: a p2p only runs
    when BOTH resolve. A non-zero fixed fee lets the perspective test assert the
    sender is charged while the recipient is not.
    """
    from app.modules.limits.schemas import LimitConfigCreateRequest
    from app.modules.limits.service import create_limit_config
    from app.modules.pricing.schemas import PricingConfigCreateRequest
    from app.modules.pricing.service import create_pricing_config

    await create_pricing_config(
        session,
        PricingConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("5"),
        ),
    )
    await create_limit_config(
        session,
        LimitConfigCreateRequest(
            tenant_id=tenant_id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )
    await session.commit()


@pytest.mark.asyncio
async def test_me_wallet_returns_caller_accounts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a signed-in customer sees their own accounts"""
    # Give the user a ZAR financial wallet so accounts is non-empty.
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_POINTS,
            currency="PTS",
        )
    )
    await db_session.commit()

    response = await async_client.get("/api/v1/identity/me/wallet", headers=alice_auth_header)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == str(test_user.id)
    assert body["tenant_id"] == str(test_user.tenant_id)
    account_types = {a["account_type"] for a in body["accounts"]}
    assert ACCOUNT_TYPE_FINANCIAL_WALLET in account_types
    assert ACCOUNT_TYPE_POINTS in account_types


@pytest.mark.asyncio
async def test_me_wallet_transaction_exposes_fee_commission_tax(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify each recent transaction shows its fee, commission, and tax"""
    from decimal import Decimal

    from app.modules.payments.service import fund

    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    await db_session.commit()
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="seed-me-wallet-fee-fields",
    )
    await db_session.commit()

    response = await async_client.get("/api/v1/identity/me/wallet", headers=alice_auth_header)
    assert response.status_code == 200, response.text
    txns = response.json()["recent_transactions"]
    assert txns, "expected at least one recent transaction"
    row = txns[0]
    # Present and zero for a plain fund (no charges). A system-funded row has no
    # user initiator, so the per-party perspective renders these as "0" (see
    # `_build_recent_txns_payload`); compare numerically to stay format-agnostic.
    assert Decimal(row["fee_amount"]) == 0
    assert Decimal(row["commission_amount"]) == 0
    assert Decimal(row["tax_amount"]) == 0


@pytest.mark.asyncio
async def test_me_wallet_transaction_exposes_reference(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify each recent transaction shows its customer-facing reference"""
    import re
    from decimal import Decimal

    from app.modules.payments.service import fund

    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    await db_session.commit()
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="seed-me-wallet-reference",
    )
    await db_session.commit()

    response = await async_client.get("/api/v1/identity/me/wallet", headers=alice_auth_header)
    assert response.status_code == 200, response.text
    txns = response.json()["recent_transactions"]
    assert txns, "expected at least one recent transaction"
    assert re.match(r"^S_\d{14}\d{6,}$", txns[0]["reference"]), txns[0]["reference"]


@pytest.mark.asyncio
async def test_me_wallet_fee_shown_to_sender_not_recipient(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify only the sender is charged the p2p fee; the recipient sees zero

    A p2p transfer carries one fee, paid by the SENDER. Both parties see the
    same transaction in their feed, but the fee (and tax) must appear only on
    the payer's side — the recipient sees "0" — and neither sees a commission
    on a plain p2p.
    """
    from app.modules.payments.service import fund, p2p_transfer

    # Sender = test_user (has the default p2p role). Give them a funded wallet.
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    # Recipient — passive party with a wallet + phone so p2p can resolve them.
    recipient = User(tenant_id=test_tenant.id)
    db_session.add(recipient)
    await db_session.flush()
    recipient_phone = "+27 82 555 7777"
    db_session.add(
        UserIdentifier(
            user_id=recipient.id,
            tenant_id=test_tenant.id,
            identifier_type="phone",
            identifier_value=recipient_phone,
            verified=True,
        )
    )
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=recipient.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    await db_session.commit()

    await _seed_p2p_fee_config(db_session, test_tenant.id)
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="seed-perspective-fund",
    )
    await db_session.commit()

    # sender_principal=None skips the step-up PIN prompt (internal call path).
    await p2p_transfer(
        db_session,
        tenant_id=test_tenant.id,
        sender_user_id=test_user.id,
        recipient_identifier_type="phone",
        recipient_identifier_value=recipient_phone,
        amount=Decimal("20"),
        currency="ZAR",
        idempotency_key="perspective-p2p-1",
    )
    await db_session.commit()

    # --- Sender's feed: the p2p row shows the fee they paid, no commission. ---
    sender_resp = await async_client.get("/api/v1/identity/me/wallet", headers=alice_auth_header)
    assert sender_resp.status_code == 200, sender_resp.text
    sender_p2p = next(
        r for r in sender_resp.json()["recent_transactions"] if r["transaction_type"] == "p2p"
    )
    assert sender_p2p["direction"] == "out"
    assert Decimal(sender_p2p["fee_amount"]) == Decimal("5")
    assert Decimal(sender_p2p["commission_amount"]) == 0
    assert Decimal(sender_p2p["tax_amount"]) == 0

    # --- Recipient's feed: same transaction, but no fee / tax / commission. ---
    recipient_token = await create_session_token_for_user(recipient.id, recipient.tenant_id)
    recipient_resp = await async_client.get(
        "/api/v1/identity/me/wallet",
        headers={"Authorization": f"Bearer {recipient_token}"},
    )
    assert recipient_resp.status_code == 200, recipient_resp.text
    recipient_p2p = next(
        r for r in recipient_resp.json()["recent_transactions"] if r["transaction_type"] == "p2p"
    )
    assert recipient_p2p["id"] == sender_p2p["id"]
    assert recipient_p2p["direction"] == "in"
    # The recipient neither paid the fee/tax nor earned a commission on a p2p.
    assert recipient_p2p["fee_amount"] == "0"
    assert recipient_p2p["tax_amount"] == "0"
    assert recipient_p2p["commission_amount"] == "0"


@pytest.mark.asyncio
async def test_me_wallet_never_exposes_the_counterparty_phone(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a customer never sees another customer's phone number

    The counterparty phone is an ADMIN-only field. The mobile feed and the
    admin table share one payload builder, so this guards the leak.
    """
    from app.modules.payments.service import fund, p2p_transfer

    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    recipient = User(tenant_id=test_tenant.id)
    db_session.add(recipient)
    await db_session.flush()
    recipient_phone = "+27 82 555 8888"
    db_session.add(
        UserIdentifier(
            user_id=recipient.id,
            tenant_id=test_tenant.id,
            identifier_type="phone",
            identifier_value=recipient_phone,
            verified=True,
        )
    )
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=recipient.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    await db_session.commit()

    await _seed_p2p_fee_config(db_session, test_tenant.id)
    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key="seed-no-phone-leak-fund",
    )
    await db_session.commit()
    await p2p_transfer(
        db_session,
        tenant_id=test_tenant.id,
        sender_user_id=test_user.id,
        recipient_identifier_type="phone",
        recipient_identifier_value=recipient_phone,
        amount=Decimal("20"),
        currency="ZAR",
        idempotency_key="no-phone-leak-p2p-1",
    )
    await db_session.commit()

    resp = await async_client.get("/api/v1/identity/me/wallet", headers=alice_auth_header)
    assert resp.status_code == 200, resp.text
    p2p = next(r for r in resp.json()["recent_transactions"] if r["transaction_type"] == "p2p")
    assert "counterparty_phone" not in p2p
    assert recipient_phone not in resp.text


@pytest.mark.asyncio
async def test_me_wallet_no_token_is_401(async_client: AsyncClient) -> None:
    """Verify viewing the wallet requires signing in"""
    response = await async_client.get("/api/v1/identity/me/wallet")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_wallet_bad_token_is_401(async_client: AsyncClient) -> None:
    """Verify an invalid session cannot view the wallet"""
    response = await async_client.get(
        "/api/v1/identity/me/wallet",
        headers={"Authorization": "Bearer not-a-real-session-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_wallet_does_not_leak_other_users_accounts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Verify a customer never sees another customer's accounts"""
    other = User(tenant_id=test_tenant.id)
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=other.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    await db_session.commit()

    response = await async_client.get("/api/v1/identity/me/wallet", headers=alice_auth_header)
    assert response.status_code == 200
    body = response.json()
    # test_user has no accounts of its own in this test — the only account
    # in the tenant belongs to `other`. The response MUST return zero
    # accounts, not other's account.
    assert body["user_id"] == str(test_user.id)
    assert body["accounts"] == []
