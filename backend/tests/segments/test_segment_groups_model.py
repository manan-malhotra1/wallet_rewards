"""Model-level tests for segment groups and dynamic-segment columns.

Verifies the Task-1 schema: a SegmentGroup row, a Segment carrying
group_id/criteria/priority, and the user_segments.source discriminator.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Segment, SegmentGroup, Tenant, User, UserSegment


@pytest.mark.asyncio
async def test_segment_group_roundtrip_and_dynamic_segment_columns(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Verify a dynamic segment carries its group, criteria, priority and defaults"""
    group = SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty")
    db_session.add(group)
    await db_session.flush()

    segment = Segment(
        tenant_id=test_tenant.id,
        group_id=group.id,
        name="Gold",
        priority=3,
        criteria={
            "v": 1,
            "op": "AND",
            "conditions": [{"metric": "txn_count", "window_days": 90, "gte": 20}],
        },
    )
    db_session.add(segment)
    await db_session.flush()

    membership = UserSegment(user_id=test_user.id, segment_id=segment.id, source="criteria")
    db_session.add(membership)
    await db_session.flush()

    row = (await db_session.execute(select(Segment).where(Segment.id == segment.id))).scalar_one()
    assert row.group_id == group.id
    assert row.priority == 3
    assert row.criteria["conditions"][0]["metric"] == "txn_count"
    assert row.is_system is False
    assert row.last_evaluated_at is None

    m = (
        await db_session.execute(select(UserSegment).where(UserSegment.segment_id == segment.id))
    ).scalar_one()
    assert m.source == "criteria"


@pytest.mark.asyncio
async def test_segment_group_name_unique_per_tenant_only(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """Verify the same group name is allowed across different tenants"""
    db_session.add(SegmentGroup(tenant_id=test_tenant.id, name="Loyalty"))
    db_session.add(SegmentGroup(tenant_id=other_tenant.id, name="Loyalty"))
    await db_session.flush()  # different tenants: OK

    rows = (
        (
            await db_session.execute(
                select(SegmentGroup).where(
                    SegmentGroup.name == "Loyalty",
                    SegmentGroup.tenant_id.in_([test_tenant.id, other_tenant.id]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert {r.tenant_id for r in rows} == {test_tenant.id, other_tenant.id}


@pytest.mark.asyncio
async def test_segment_group_name_unique_within_tenant(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a duplicate group name in the same tenant violates the unique constraint"""
    db_session.add(SegmentGroup(tenant_id=test_tenant.id, name="Loyalty"))
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(SegmentGroup(tenant_id=test_tenant.id, name="Loyalty"))
            await db_session.flush()


@pytest.mark.asyncio
async def test_segment_group_query_is_tenant_scoped(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """Verify a tenant-scoped group query never returns another tenant's groups"""
    db_session.add(SegmentGroup(tenant_id=test_tenant.id, name="Customer Loyalty"))
    db_session.add(SegmentGroup(tenant_id=other_tenant.id, name="Merchant Tiers"))
    await db_session.flush()

    rows = (
        (
            await db_session.execute(
                select(SegmentGroup).where(SegmentGroup.tenant_id == other_tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert [r.name for r in rows] == ["Merchant Tiers"]
