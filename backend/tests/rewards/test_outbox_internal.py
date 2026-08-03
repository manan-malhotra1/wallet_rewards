"""Internal wallet → rewards outbox behavior."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.shared.models import Transaction
from app.shared.models.rewards import OUTBOX_PENDING, RewardOutbox


@pytest.mark.asyncio
async def test_outbox_row_is_tenant_scoped(db_session, tenant_factory):
    """Verify a reward-outbox row for one tenant is invisible to another tenant."""
    # Two independent tenants — the outbox row belongs to tenant A only.
    tenant_a = await tenant_factory(business_type="both")
    tenant_b = await tenant_factory(business_type="both")

    # The outbox FK targets transactions.id, so a real transaction must exist.
    # A minimal row (only the NOT NULL columns without defaults) satisfies it;
    # we are asserting tenant isolation, not exercising post_transaction.
    txn = Transaction(
        tenant_id=tenant_a.id,
        idempotency_key=f"outbox-test-{uuid4().hex}",
        transaction_type="p2p",
        amount=100,
        currency="ZAR",
    )
    db_session.add(txn)
    await db_session.flush()

    outbox = RewardOutbox(
        tenant_id=tenant_a.id,
        user_id=uuid4(),
        transaction_id=txn.id,
        transaction_type="p2p",
        amount=100,
        currency="ZAR",
    )
    db_session.add(outbox)
    await db_session.commit()

    # Querying under tenant B's id must return nothing.
    seen_by_b = (
        await db_session.execute(
            select(RewardOutbox).where(RewardOutbox.tenant_id == tenant_b.id)
        )
    ).scalars().all()
    assert seen_by_b == []

    # Tenant A sees exactly its own pending row.
    seen_by_a = (
        await db_session.execute(
            select(RewardOutbox).where(RewardOutbox.tenant_id == tenant_a.id)
        )
    ).scalars().all()
    assert len(seen_by_a) == 1
    assert seen_by_a[0].id == outbox.id
    assert seen_by_a[0].status == OUTBOX_PENDING
