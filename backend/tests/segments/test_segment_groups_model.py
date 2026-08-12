"""Model-level tests for segment groups and dynamic-segment columns.

Verifies the Task-1 schema: a SegmentGroup row, a Segment carrying
group_id/criteria/priority, and the user_segments.source discriminator.
"""
import pytest
from sqlalchemy import select

from app.shared.models import Segment, SegmentGroup, UserSegment


@pytest.mark.asyncio
async def test_segment_group_roundtrip_and_dynamic_segment_columns(
    db_session, test_tenant, test_user
):
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

    membership = UserSegment(
        user_id=test_user.id, segment_id=segment.id, source="criteria"
    )
    db_session.add(membership)
    await db_session.flush()

    row = (
        await db_session.execute(select(Segment).where(Segment.id == segment.id))
    ).scalar_one()
    assert row.group_id == group.id
    assert row.priority == 3
    assert row.criteria["conditions"][0]["metric"] == "txn_count"
    assert row.is_system is False
    assert row.last_evaluated_at is None

    m = (
        await db_session.execute(
            select(UserSegment).where(UserSegment.segment_id == segment.id)
        )
    ).scalar_one()
    assert m.source == "criteria"


@pytest.mark.asyncio
async def test_segment_group_name_unique_per_tenant_only(
    db_session, test_tenant, other_tenant
):
    db_session.add(SegmentGroup(tenant_id=test_tenant.id, name="Loyalty"))
    db_session.add(SegmentGroup(tenant_id=other_tenant.id, name="Loyalty"))
    await db_session.flush()  # different tenants: OK
    assert True
