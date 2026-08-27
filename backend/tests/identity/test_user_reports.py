"""A supervisor can see who reports to them (spec B12.2).

The hierarchy was only ever readable upwards — a user knew their supervisor,
but a supervisor could not see who fed them. Since parent commission pays a
supervisor off that same link, an operator reconciling a commission run had no
way to answer "which agents feed this super-agent?" without querying the
database.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.service import list_user_reports
from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.exceptions import UserNotFound
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_COMMISSION_WALLET,
    Account,
    Tenant,
    User,
)
from tests.fixtures.commission import BatchFixture


async def _child(
    session: AsyncSession, tenant: Tenant, parent: User, user_type: str = "agent"
) -> User:
    """A user hanging under `parent`."""
    user = User(tenant_id=tenant.id, user_type=user_type, parent_user_id=parent.id)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_a_supervisor_sees_their_reports(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """The direction that was previously unreadable."""
    supervisor = User(tenant_id=batch_fixture.tenant.id, user_type="super_agent")
    db_session.add(supervisor)
    await db_session.commit()
    await db_session.refresh(supervisor)

    for _ in range(3):
        await _child(db_session, batch_fixture.tenant, supervisor)

    rows, total = await list_user_reports(
        db_session, tenant_id=batch_fixture.tenant.id, user_id=supervisor.id
    )
    assert total == 3
    assert len(rows) == 3
    assert all(r["user_type"] == "agent" for r in rows)


@pytest.mark.asyncio
async def test_a_user_with_no_downline_reports_nobody(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """An empty downline is a normal state, not an error."""
    rows, total = await list_user_reports(
        db_session, tenant_id=batch_fixture.tenant.id, user_id=batch_fixture.agent.id
    )
    assert rows == []
    assert total == 0


@pytest.mark.asyncio
async def test_a_child_in_another_tenant_never_appears(
    db_session: AsyncSession, batch_fixture: BatchFixture, other_tenant: Tenant
) -> None:
    """Tenant isolation (NFR-0220).

    `users.parent_user_id` carries no tenant of its own, so the tenant filter is
    the ONLY thing preventing a cross-tenant child from being listed.
    """
    supervisor = User(tenant_id=batch_fixture.tenant.id, user_type="super_agent")
    db_session.add(supervisor)
    await db_session.commit()
    await db_session.refresh(supervisor)

    await _child(db_session, batch_fixture.tenant, supervisor)
    # A foreign user pointing at the same supervisor id.
    foreign = User(
        tenant_id=other_tenant.id, user_type="agent", parent_user_id=supervisor.id
    )
    db_session.add(foreign)
    await db_session.commit()

    rows, total = await list_user_reports(
        db_session, tenant_id=batch_fixture.tenant.id, user_id=supervisor.id
    )
    assert total == 1
    assert foreign.id not in {r["id"] for r in rows}


@pytest.mark.asyncio
async def test_an_unknown_supervisor_is_a_404(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """No existence leak across tenants."""
    with pytest.raises(UserNotFound):
        await list_user_reports(
            db_session, tenant_id=batch_fixture.tenant.id, user_id=uuid4()
        )


@pytest.mark.asyncio
async def test_each_report_carries_its_accrued_commission(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """The reconciliation question: who feeds this, and by how much?

    A bare name list would stop one step short of what an operator checking a
    commission run actually needs.
    """
    from sqlalchemy import select

    supervisor = User(tenant_id=batch_fixture.tenant.id, user_type="super_agent")
    db_session.add(supervisor)
    await db_session.commit()
    await db_session.refresh(supervisor)

    child = await _child(db_session, batch_fixture.tenant, supervisor)
    wallet = Account(
        tenant_id=batch_fixture.tenant.id,
        user_id=child.id,
        account_type=ACCOUNT_TYPE_COMMISSION_WALLET,
        currency="ZAR",
    )
    db_session.add(wallet)
    await db_session.commit()
    await db_session.refresh(wallet)

    pool = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == batch_fixture.tenant.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION,
                Account.currency == "ZAR",
            )
        )
    ).scalars().first()

    accrued = Decimal("12.5")
    await post_transaction(
        db_session,
        PostTransactionRequest(
            tenant_id=batch_fixture.tenant.id,
            idempotency_key=f"rep-{uuid4().hex[:10]}",
            transaction_type="commission_accrual",
            currency="ZAR",
            amount=accrued,
            entries=[
                LedgerEntryRequest(pool.id, "DEBIT", accrued),
                LedgerEntryRequest(wallet.id, "CREDIT", accrued),
            ],
        ),
    )

    rows, _ = await list_user_reports(
        db_session, tenant_id=batch_fixture.tenant.id, user_id=supervisor.id
    )
    assert Decimal(rows[0]["accrued_commission"]["ZAR"]) == accrued


@pytest.mark.asyncio
async def test_reports_paginate(
    db_session: AsyncSession, batch_fixture: BatchFixture
) -> None:
    """A large downline must not load in one page."""
    supervisor = User(tenant_id=batch_fixture.tenant.id, user_type="super_agent")
    db_session.add(supervisor)
    await db_session.commit()
    await db_session.refresh(supervisor)
    for _ in range(5):
        await _child(db_session, batch_fixture.tenant, supervisor)

    page1, total = await list_user_reports(
        db_session, tenant_id=batch_fixture.tenant.id, user_id=supervisor.id, limit=2
    )
    page2, _ = await list_user_reports(
        db_session,
        tenant_id=batch_fixture.tenant.id,
        user_id=supervisor.id,
        limit=2,
        offset=2,
    )
    assert total == 5
    assert len(page1) == 2
    assert len(page2) == 2
    assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in page2})
