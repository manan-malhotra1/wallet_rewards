"""Tests for the multipliers module — CRUD + hot-path resolution."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.multipliers.service import resolve_multiplier_for_issuance
from app.shared.models import (
    BonusMultiplier,
    Segment,
    Tenant,
    User,
    UserSegment,
)


@pytest.mark.asyncio
async def test_no_multipliers_returns_one(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Empty table → resolver returns 1.00."""
    m = await resolve_multiplier_for_issuance(
        db_session,
        tenant_id=test_tenant.id,
        rule_id=uuid4(),
        user_id=test_user.id,
    )
    assert m == Decimal("1.00")


@pytest.mark.asyncio
async def test_global_multiplier_applies(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Tenant-global multiplier (NULL rule + NULL segment) applies to everyone."""
    db_session.add(
        BonusMultiplier(
            tenant_id=test_tenant.id,
            multiplier=Decimal("2.00"),
        )
    )
    await db_session.commit()
    m = await resolve_multiplier_for_issuance(
        db_session,
        tenant_id=test_tenant.id,
        rule_id=uuid4(),
        user_id=test_user.id,
    )
    assert m == Decimal("2.00")


@pytest.mark.asyncio
async def test_outside_window_does_not_apply(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Multiplier with `valid_until` in the past → not applied."""
    db_session.add(
        BonusMultiplier(
            tenant_id=test_tenant.id,
            multiplier=Decimal("3.00"),
            valid_until=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db_session.commit()
    m = await resolve_multiplier_for_issuance(
        db_session,
        tenant_id=test_tenant.id,
        rule_id=uuid4(),
        user_id=test_user.id,
    )
    assert m == Decimal("1.00")


@pytest.mark.asyncio
async def test_segment_multiplier_requires_membership(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """A segment-bound multiplier only applies to users in the segment."""
    segment = Segment(tenant_id=test_tenant.id, name=f"seg-{uuid4().hex[:6]}")
    db_session.add(segment)
    await db_session.commit()
    await db_session.refresh(segment)

    db_session.add(
        BonusMultiplier(
            tenant_id=test_tenant.id,
            segment_id=segment.id,
            multiplier=Decimal("5.00"),
        )
    )
    await db_session.commit()

    # User NOT in segment → no multiplier.
    m_no = await resolve_multiplier_for_issuance(
        db_session,
        tenant_id=test_tenant.id,
        rule_id=uuid4(),
        user_id=test_user.id,
    )
    assert m_no == Decimal("1.00")

    # Add membership → multiplier applies.
    db_session.add(UserSegment(user_id=test_user.id, segment_id=segment.id))
    await db_session.commit()

    m_yes = await resolve_multiplier_for_issuance(
        db_session,
        tenant_id=test_tenant.id,
        rule_id=uuid4(),
        user_id=test_user.id,
    )
    assert m_yes == Decimal("5.00")


@pytest.mark.asyncio
async def test_biggest_multiplier_wins(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """When multiple multipliers match, the largest applies (no stacking)."""
    db_session.add_all(
        [
            BonusMultiplier(tenant_id=test_tenant.id, multiplier=Decimal("2.00")),
            BonusMultiplier(tenant_id=test_tenant.id, multiplier=Decimal("3.00")),
            BonusMultiplier(tenant_id=test_tenant.id, multiplier=Decimal("1.50")),
        ]
    )
    await db_session.commit()
    m = await resolve_multiplier_for_issuance(
        db_session,
        tenant_id=test_tenant.id,
        rule_id=uuid4(),
        user_id=test_user.id,
    )
    assert m == Decimal("3.00")


@pytest.mark.asyncio
async def test_admin_create_multiplier_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """POST /multipliers returns 201."""
    resp = await async_client.post(
        "/api/v1/multipliers",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "multiplier": "1.5"},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_admin_create_rejects_inverted_window(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """valid_from >= valid_until → 422."""
    resp = await async_client.post(
        "/api/v1/multipliers",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "multiplier": "2",
            "valid_from": "2026-12-31T00:00:00Z",
            "valid_until": "2026-01-01T00:00:00Z",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_create_rejects_nonpositive_multiplier(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """multiplier <= 0 → 422."""
    resp = await async_client.post(
        "/api/v1/multipliers",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "multiplier": "0"},
    )
    assert resp.status_code == 422
