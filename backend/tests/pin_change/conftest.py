"""Fixtures for the change-PIN tests.

Builds a consumer with a known PIN + phone + a funded ZAR wallet, a session
token, and the pricing / limit / tax configs used by the fee, zero-fee, and
fail-closed (invariant #12) scenarios. Change-PIN is NOT role-gated, so no role
fixtures are needed — the current-PIN check is the only gate.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.hashing import hash_pin
from app.modules.ledger import LedgerEntryRequest, PostTransactionRequest, post_transaction
from app.modules.limits.schemas import LimitConfigCreateRequest
from app.modules.limits.service import create_limit_config
from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import create_pricing_config
from app.modules.taxes.schemas import TaxConfigCreateRequest
from app.modules.taxes.service import create_tax_config
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    TXN_STATUS_COMPLETED,
    USER_TYPE_CONSUMER,
    Account,
    Tenant,
    User,
    UserIdentifier,
)

PIN_USER_PHONE = "+27 82 555 2000"
CURRENT_PIN = "1234"
NEW_PIN = "5678"


async def _fund(session: AsyncSession, tenant: Tenant, wallet: Account, amount: Decimal) -> None:
    """Credit a wallet with a COMPLETED cash-inflow leg (test funding helper)."""
    inflow = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
                Account.currency == wallet.currency,
                Account.user_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if inflow is None:
        inflow = Account(
            tenant_id=tenant.id,
            account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
            currency=wallet.currency,
        )
        session.add(inflow)
        await session.flush()
    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=f"fund-{wallet.id}",
            transaction_type="fund",
            currency=wallet.currency,
            status=TXN_STATUS_COMPLETED,
            entries=[
                LedgerEntryRequest(account_id=inflow.id, entry_type=ENTRY_DEBIT, amount=amount),
                LedgerEntryRequest(account_id=wallet.id, entry_type=ENTRY_CREDIT, amount=amount),
            ],
        ),
    )


@pytest_asyncio.fixture
async def pin_user(db_session: AsyncSession, test_tenant: Tenant) -> User:
    """A consumer with a known current PIN and a phone identifier."""
    user = User(
        tenant_id=test_tenant.id,
        user_type=USER_TYPE_CONSUMER,
        pin_hash=hash_pin(CURRENT_PIN),
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=test_tenant.id,
            identifier_type="phone",
            identifier_value=PIN_USER_PHONE,
            verified=True,
        )
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def pin_user_wallet(db_session: AsyncSession, test_tenant: Tenant, pin_user: User) -> Account:
    """The user's ZAR financial wallet, funded with R100."""
    wallet = Account(
        tenant_id=test_tenant.id,
        user_id=pin_user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    db_session.add(wallet)
    await db_session.commit()
    await db_session.refresh(wallet)
    await _fund(db_session, test_tenant, wallet, Decimal("100"))
    return wallet


@pytest_asyncio.fixture
async def pin_auth_header(pin_user: User) -> dict[str, str]:
    """Session token bound to pin_user."""
    from app.auth.sessions import create_session

    token = await create_session(pin_user.id, pin_user.tenant_id, "mobile")
    return {"Authorization": f"Bearer {token}"}


async def _add_pricing(session: AsyncSession, tenant: Tenant, fee: Decimal) -> None:
    """Create the change_pin pricing config (NULL user_type) with a fixed fee."""
    await create_pricing_config(
        session,
        PricingConfigCreateRequest(
            tenant_id=tenant.id,
            transaction_type="change_pin",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=fee,
            fee_inclusive=False,
        ),
    )


async def _add_limit(session: AsyncSession, tenant: Tenant) -> None:
    """Create a permissive change_pin limit config (satisfies the #12 gate)."""
    await create_limit_config(
        session,
        LimitConfigCreateRequest(
            tenant_id=tenant.id,
            transaction_type="change_pin",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            daily_count_cap=10,
        ),
    )


@pytest_asyncio.fixture
async def fee_configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Pricing (R2 fee) + limit + 15% tax → fee 2, fee-tax 0.30 (charged path)."""
    await _add_pricing(db_session, test_tenant, Decimal("2"))
    await _add_limit(db_session, test_tenant)
    await create_tax_config(
        db_session,
        TaxConfigCreateRequest(
            tenant_id=test_tenant.id,
            currency="ZAR",
            fee_tax_pct=Decimal("0.15"),
            commission_tax_pct=Decimal("0.15"),
            fee_tax_inclusive=False,
            commission_tax_inclusive=False,
        ),
    )


@pytest_asyncio.fixture
async def zero_fee_configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Explicit R0 pricing + limit — a zero-fee change (no ledger legs)."""
    await _add_pricing(db_session, test_tenant, Decimal("0"))
    await _add_limit(db_session, test_tenant)


@pytest_asyncio.fixture
async def pricing_only_configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Pricing present, limit MISSING — for the invariant #12 fail-closed test."""
    await _add_pricing(db_session, test_tenant, Decimal("0"))


@pytest_asyncio.fixture
async def limit_only_configs(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Limit present, pricing MISSING — for the invariant #12 fail-closed test."""
    await _add_limit(db_session, test_tenant)


def change_pin_body(current: str = CURRENT_PIN, new: str = NEW_PIN) -> dict:
    """A change-PIN request body."""
    return {"current_pin": current, "new_pin": new, "currency": "ZAR"}


def change_pin_headers(auth: dict[str, str], idem: str | None = None) -> dict[str, str]:
    return {
        **auth,
        "Idempotency-Key": idem or f"pinchg-{uuid4().hex[:12]}",
        "Content-Type": "application/json",
    }
