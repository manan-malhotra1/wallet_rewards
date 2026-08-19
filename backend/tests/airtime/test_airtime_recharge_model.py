"""Airtime recharge records.

The `AirtimeRecharge` model existed in the tree but was never registered in
`shared/models/__init__.py` nor given a table migration, so `airtime_recharges`
did not exist. These tests lock that the table now exists, is tenant-scoped, and
enforces per-tenant idempotency.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    AIRTIME_STATUS_PENDING,
    TXN_STATUS_PENDING,
    AirtimeRecharge,
    Tenant,
    Transaction,
    User,
)


async def _make_pending_txn(session: AsyncSession, tenant: Tenant, key: str) -> Transaction:
    """A minimal PENDING transaction to satisfy the recharge FK."""
    txn = Transaction(
        tenant_id=tenant.id,
        idempotency_key=key,
        transaction_type="airtime_recharge",
        # NOT NULL since migration 0056 (base/derived services) — this helper
        # constructs the row directly rather than through post_transaction, so
        # it must supply the column itself. This is the endpoint's own base.
        base_transaction_type="airtime_recharge",
        currency="ZAR",
        amount=Decimal("10"),
        status=TXN_STATUS_PENDING,
    )
    session.add(txn)
    await session.flush()
    return txn


@pytest.mark.asyncio
async def test_airtime_recharge_persists_pending(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Verify a new airtime recharge is saved and starts as pending"""
    txn = await _make_pending_txn(db_session, test_tenant, "rc-1")
    recharge = AirtimeRecharge(
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        msisdn="+27825551234",
        network="MTN",
        amount=Decimal("10"),
        currency="ZAR",
        transaction_id=txn.id,
        idempotency_key="rc-1",
    )
    db_session.add(recharge)
    await db_session.commit()
    await db_session.refresh(recharge)

    assert recharge.status == AIRTIME_STATUS_PENDING
    assert recharge.network == "MTN"


@pytest.mark.asyncio
async def test_airtime_recharge_idempotency_key_unique_per_tenant(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Verify two recharges with the same idempotency key in a tenant are rejected"""
    txn1 = await _make_pending_txn(db_session, test_tenant, "txn-a")
    db_session.add(
        AirtimeRecharge(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            msisdn="+27825551234",
            network="MTN",
            amount=Decimal("10"),
            currency="ZAR",
            transaction_id=txn1.id,
            idempotency_key="dup",
        )
    )
    await db_session.commit()

    txn2 = await _make_pending_txn(db_session, test_tenant, "txn-b")
    db_session.add(
        AirtimeRecharge(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            msisdn="+27825551234",
            network="MTN",
            amount=Decimal("10"),
            currency="ZAR",
            transaction_id=txn2.id,
            idempotency_key="dup",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_airtime_recharge_is_tenant_scoped(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant, test_user: User
) -> None:
    """Verify a recharge in one tenant is invisible to another tenant"""
    txn = await _make_pending_txn(db_session, test_tenant, "rc-iso")
    db_session.add(
        AirtimeRecharge(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            msisdn="+27825551234",
            network="MTN",
            amount=Decimal("10"),
            currency="ZAR",
            transaction_id=txn.id,
            idempotency_key="rc-iso",
        )
    )
    await db_session.commit()

    rows = (
        (
            await db_session.execute(
                select(AirtimeRecharge).where(AirtimeRecharge.tenant_id == other_tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []
