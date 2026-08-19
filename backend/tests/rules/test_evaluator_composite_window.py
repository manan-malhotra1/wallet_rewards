"""Composite time-window enforcement (Pay-PRD-0619).

An AND composite's sub-conditions must be satisfied *within the rule's
time_window* — qualifying transactions older than the window must not count.
Uses the same internal wallet-outbox drive + direct `transactions` seeding as
`test_evaluator_composite.py`: the composite evaluator counts COMPLETED
transactions, and the driving event's own amount is irrelevant.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.schemas import NormalisedEvent
from app.modules.events.service import evaluate_and_issue_firings
from app.shared.models import (
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    TXN_STATUS_COMPLETED,
    Account,
    Tenant,
    Transaction,
    User,
)

_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
_TWO_CONDS = [
    {"transaction_type": "fund", "count_threshold": 1},
    {"transaction_type": "send", "count_threshold": 1},
]


async def _create_composite_rule(client: AsyncClient, tenant: Tenant, *, time_window: str) -> None:
    """Create an AND composite rule with a time window via the API."""
    resp = await client.post(
        "/api/v1/rules",
        json={
            "tenant_id": str(tenant.id),
            "name": f"composite-win-{uuid4().hex[:6]}",
            "rule_type": "composite",
            "composite_operator": "AND",
            "conditions": _TWO_CONDS,
            "time_window": time_window,
            "reward_type": "points",
            "reward_value": "100",
        },
    )
    assert resp.status_code == 201, resp.text


def _txn(tenant: Tenant, user: User, *, txn_type: str, when: datetime) -> Transaction:
    """Build one COMPLETED transaction the composite evaluator will count."""
    txn = Transaction(
        tenant_id=tenant.id,
        idempotency_key=uuid4().hex,
        transaction_type=txn_type,
        status=TXN_STATUS_COMPLETED,
        initiated_by=user.id,
        amount=Decimal("500"),
        currency="ZAR",
    )
    txn.created_at = when
    return txn


async def _seed(
    session: AsyncSession, tenant: Tenant, user: User, *, txns: list[Transaction]
) -> None:
    """Seed points accounts + qualifying transactions in a single commit."""
    session.add(
        Account(
            tenant_id=tenant.id,
            account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            currency="PTS",
        )
    )
    session.add(
        Account(
            tenant_id=tenant.id,
            user_id=user.id,
            account_type="points_account",
            currency="PTS",
        )
    )
    for txn in txns:
        session.add(txn)
    await session.commit()


async def _ingest(session: AsyncSession, tenant: Tenant, user: User, *, at: datetime) -> int:
    """Drive one 'send' wallet event through the evaluator; return firings."""
    event = NormalisedEvent(
        event_id=uuid4().hex,
        source_key="internal:wallet",
        tenant_id=tenant.id,
        user_id=user.id,
        transaction_type="send",
        amount=Decimal("1"),
        currency="ZAR",
        merchant_id=None,
        timestamp=at,
    )
    return len(await evaluate_and_issue_firings(session, event))


@pytest.mark.asyncio
async def test_composite_rolling_7d_ignores_transactions_outside_window(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify an AND composite does not count a transaction older than 7 days"""
    await _create_composite_rule(async_client, test_tenant, time_window="rolling_7d")
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", when=_NOW - timedelta(days=10)),
            _txn(test_tenant, test_user, txn_type="send", when=_NOW),
        ],
    )

    # The fund leg is 10 days old → outside the window → AND unsatisfied.
    assert await _ingest(db_session, test_tenant, test_user, at=_NOW) == 0

    # A fresh fund inside the window completes the AND.
    db_session.add(_txn(test_tenant, test_user, txn_type="fund", when=_NOW))
    await db_session.commit()
    assert await _ingest(db_session, test_tenant, test_user, at=_NOW) == 1


@pytest.mark.asyncio
async def test_composite_calendar_month_only_counts_current_month(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify an AND composite does not count last month's transactions"""
    await _create_composite_rule(async_client, test_tenant, time_window="calendar_month")
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", when=datetime(2026, 5, 30, tzinfo=UTC)),
            _txn(test_tenant, test_user, txn_type="send", when=_NOW),
        ],
    )

    # The fund leg landed in May → outside June's window.
    assert await _ingest(db_session, test_tenant, test_user, at=_NOW) == 0

    db_session.add(_txn(test_tenant, test_user, txn_type="fund", when=_NOW))
    await db_session.commit()
    assert await _ingest(db_session, test_tenant, test_user, at=_NOW) == 1


@pytest.mark.asyncio
async def test_composite_lifetime_counts_old_transactions(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify a lifetime composite still counts arbitrarily old transactions"""
    await _create_composite_rule(async_client, test_tenant, time_window="lifetime")
    await _seed(
        db_session,
        test_tenant,
        test_user,
        txns=[
            _txn(test_tenant, test_user, txn_type="fund", when=_NOW - timedelta(days=60)),
            _txn(test_tenant, test_user, txn_type="send", when=_NOW),
        ],
    )

    assert await _ingest(db_session, test_tenant, test_user, at=_NOW) == 1
