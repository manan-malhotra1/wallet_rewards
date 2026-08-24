"""Structural tests for the user-type catalog models."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, UserTypeCategory, UserTypeDef


@pytest.mark.asyncio
async def test_seeded_categories_and_system_types_exist(db_session: AsyncSession) -> None:
    """Verify the migration seeded three categories and five system types."""
    stmt = select(UserTypeCategory).order_by(UserTypeCategory.display_order)
    categories = (await db_session.execute(stmt)).scalars().all()
    assert [c.code for c in categories] == ["consumer", "retail", "business"]
    assert [c.supports_hierarchy for c in categories] == [False, True, True]

    types = (
        (await db_session.execute(select(UserTypeDef).where(UserTypeDef.tenant_id.is_(None))))
        .scalars()
        .all()
    )
    by_code = {t.code: t for t in types}
    assert set(by_code) == {"consumer", "agent", "super_agent", "merchant", "head_merchant"}
    assert by_code["agent"].parent_type_code == "super_agent"
    assert by_code["merchant"].parent_type_code == "head_merchant"
    assert by_code["super_agent"].parent_type_code is None
    # Merchant capability is no longer a column — it is Business membership, so
    # the seed must file the two merchant types under that category and nothing
    # else under it. Same assertion, moved to where the meaning now lives.
    assert by_code["merchant"].category_code == "business"
    assert by_code["head_merchant"].category_code == "business"
    assert by_code["consumer"].category_code == "consumer"
    assert {c for c, t in by_code.items() if t.category_code == "business"} == {
        "merchant",
        "head_merchant",
    }
    assert all(t.is_system for t in types)


@pytest.mark.asyncio
async def test_self_parent_is_rejected_by_check(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a type cannot name itself as its own parent."""
    db_session.add(
        UserTypeDef(
            tenant_id=test_tenant.id,
            code="loop",
            label="Loop",
            category_code="retail",
            parent_type_code="loop",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_tenant_cannot_duplicate_its_own_code(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify (tenant_id, code) is unique for tenant-scoped types."""
    for _ in range(2):
        db_session.add(
            UserTypeDef(
                tenant_id=test_tenant.id,
                code="distributor",
                label="Distributor",
                category_code="retail",
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
