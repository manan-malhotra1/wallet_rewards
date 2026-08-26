"""Single-user withdrawal can target a commission wallet (spec §9).

Lets an administrator claw back one agent's accrued commission through the same
Epic 18 maker-checker flow used for every other treasury movement.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.treasury.service import resolve_user_wallet
from app.shared.exceptions import AccountNotFound
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
)
from tests.commission_batches.conftest import BatchFixture


@pytest.mark.asyncio
async def test_resolves_the_commission_wallet_when_asked(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """Explicitly asking for the commission wallet returns it."""
    _, account = await resolve_user_wallet(
        db_session,
        batch_fixture.tenant.id,
        "phone",
        batch_fixture.agent_msisdn,
        "ZAR",
        wallet_type="commission_wallet",
    )
    assert account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET
    assert account.id == batch_fixture.agent_commission_wallet.id


@pytest.mark.asyncio
async def test_defaults_to_the_main_wallet(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """Existing callers pass no wallet_type and must keep working unchanged."""
    _, account = await resolve_user_wallet(
        db_session,
        batch_fixture.tenant.id,
        "phone",
        batch_fixture.agent_msisdn,
        "ZAR",
    )
    assert account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET


@pytest.mark.asyncio
async def test_missing_commission_wallet_is_a_404(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """The consumer holds no commission wallet, so resolution fails cleanly."""
    with pytest.raises(AccountNotFound):
        await resolve_user_wallet(
            db_session,
            batch_fixture.tenant.id,
            "phone",
            batch_fixture.consumer_msisdn,
            "ZAR",
            wallet_type="commission_wallet",
        )


@pytest.mark.asyncio
async def test_withdraw_payload_defaults_to_main_wallet() -> None:
    """A payload STORED before this edition still validates and targets main.

    This is why `wallet_type` is defaulted rather than required: money-operation
    payloads are re-validated at APPROVAL time, potentially days after they were
    written.
    """
    from app.modules.money_operations.schemas import WithdrawUserPayload

    payload = WithdrawUserPayload.model_validate(
        {
            "identifier_type": "phone",
            "identifier_value": "+27821110000",
            "amount": "10",
            "currency": "ZAR",
            "bank_mirror_account_id": "11111111-1111-4000-8000-000000000001",
        }
    )
    assert payload.wallet_type == "main_wallet"


@pytest.mark.asyncio
async def test_withdraw_payload_accepts_commission_wallet() -> None:
    """The new option validates."""
    from app.modules.money_operations.schemas import WithdrawUserPayload

    payload = WithdrawUserPayload.model_validate(
        {
            "identifier_type": "phone",
            "identifier_value": "+27821110000",
            "amount": "10",
            "currency": "ZAR",
            "bank_mirror_account_id": "11111111-1111-4000-8000-000000000001",
            "wallet_type": "commission_wallet",
        }
    )
    assert payload.wallet_type == "commission_wallet"


@pytest.mark.asyncio
async def test_withdrawing_more_than_accrued_is_refused(
    db_session: AsyncSession, batch_fixture: BatchFixture, admin_principal
) -> None:
    """The ledger floor rejects an overdraw even through the treasury path."""
    from app.modules.treasury.service import withdraw_from_user
    from app.shared.exceptions import InsufficientCommissionBalance

    with pytest.raises(InsufficientCommissionBalance):
        await withdraw_from_user(
            db_session,
            tenant_id=batch_fixture.tenant.id,
            identifier_type="phone",
            identifier_value=batch_fixture.agent_msisdn,
            amount=Decimal("500"),
            currency="ZAR",
            bank_mirror_account_id=batch_fixture.bank_mirror.id,
            reason="clawback",
            admin=admin_principal,
            wallet_type="commission_wallet",
        )
