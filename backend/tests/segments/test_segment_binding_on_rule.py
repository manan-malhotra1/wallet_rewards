"""Segment-targeted rewards."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


def _event(*, tenant: Tenant, user: User, source_key: str) -> dict:
    """Canonical RawExternalEvent body."""
    return {
        "event_id": uuid4().hex,
        "source_key": source_key,
        "tenant_id": str(tenant.id),
        "user_id": str(user.id),
        "transaction_type": "fund",
        "amount": "500",
        "currency": "ZAR",
        "timestamp": datetime.now(UTC).isoformat(),
    }


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

    # Source + segment + rule with segment binding.
    await async_client.post(
        "/api/v1/events/sources",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "name": "seg-src",
            "source_key": "seg-src",
        },
    )

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

    r1 = await async_client.post(
        "/api/v1/events/external",
        json=_event(tenant=test_tenant, user=test_user, source_key="seg-src"),
    )
    assert r1.json()["rules_fired"] == []

    # Add the user to the segment, fire another event for a clean
    # (user, rule, triggering_event_id) tuple → now fires.
    db_session.add(UserSegment(user_id=test_user.id, segment_id=segment_id))
    await db_session.commit()

    r2 = await async_client.post(
        "/api/v1/events/external",
        json=_event(tenant=test_tenant, user=test_user, source_key="seg-src"),
    )
    assert len(r2.json()["rules_fired"]) == 1
