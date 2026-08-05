"""Segment-targeted rewards.

Driven through the INTERNAL wallet-outbox path — a direct
`evaluate_and_issue_firings` call shaped like `reward_outbox` rows
(`source_key="internal:wallet"`) — because `test_tenant` is a `both`-mode
tenant, where rewards come from the wallet outbox and external HTTP ingest is
correctly rejected (`wrong_mode`). The segment + rule are still created via the
public admin API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.schemas import NormalisedEvent
from app.modules.events.service import evaluate_and_issue_firings
from app.shared.models import (
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    Rule,
    Tenant,
    User,
    UserSegment,
)


async def _ensure_system_points(session: AsyncSession, tenant: Tenant) -> None:
    """Create system_points_issuance + give the user a points wallet."""
    existing = (
        await session.execute(
            select(Account).where(
                Account.tenant_id == tenant.id,
                Account.account_type == ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Account(
                tenant_id=tenant.id,
                account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
                currency="PTS",
            )
        )
        await session.commit()


async def _ingest(session: AsyncSession, tenant: Tenant, user: User) -> int:
    """Drive one internal wallet event through the evaluator; return firings fired.

    Mirrors how `reward_outbox` shapes an event for `evaluate_and_issue_firings`:
    an `internal:wallet` source, a per-transaction event_id, no merchant. Each
    call uses a fresh event_id so a firing is never blocked by the idempotency
    guard from a prior call.
    """
    event = NormalisedEvent(
        event_id=uuid4().hex,
        source_key="internal:wallet",
        tenant_id=tenant.id,
        user_id=user.id,
        transaction_type="fund",
        amount=Decimal("500"),
        currency="ZAR",
        merchant_id=None,
        timestamp=datetime.now(UTC),
    )
    firings = await evaluate_and_issue_firings(session, event)
    return len(firings)


@pytest.mark.asyncio
async def test_segment_bound_rule_fires_only_for_members(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    user_points,
) -> None:
    """Verify a reward only applies to customers in the targeted segment"""
    await _ensure_system_points(db_session, test_tenant)

    seg_resp = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "vip-bind-test"},
    )
    segment_id = seg_resp.json()["id"]

    # Create a rule and patch its segment_id directly (admin rule-create
    # API doesn't expose segment_id yet — that's a future UI surface).
    rule_resp = await async_client.post(
        "/api/v1/rules",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "name": "vip-only-bonus",
            "rule_type": "first_time",
            "transaction_type": "fund",
            "reward_type": "points",
            "reward_value": "100",
        },
    )
    rule_id = rule_resp.json()["id"]
    rule = (await db_session.execute(select(Rule).where(Rule.id == rule_id))).scalar_one()
    rule.segment_id = segment_id
    await db_session.commit()

    # Not a member yet → the segment-bound rule is skipped.
    assert await _ingest(db_session, test_tenant, test_user) == 0

    # Add the user to the segment, fire another event for a clean
    # (user, rule, triggering_event_id) tuple → now fires.
    db_session.add(UserSegment(user_id=test_user.id, segment_id=segment_id))
    await db_session.commit()

    assert await _ingest(db_session, test_tenant, test_user) == 1
