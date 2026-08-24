"""Lookup and visibility tests for the user-type catalog."""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.service import get_user_type, list_user_types
from app.shared.models import Tenant, UserTypeDef


async def _add(session: AsyncSession, tenant: Tenant | None, code: str, **kw: Any) -> UserTypeDef:
    """Insert one type row for a test.

    Args:
        session: Async DB session.
        tenant: Owning tenant, or None for a platform-wide system type.
        code: The type code to insert.
        **kw: Column overrides — `label` and `category_code` have defaults.

    Returns:
        The flushed `UserTypeDef` row.
    """
    row = UserTypeDef(
        tenant_id=tenant.id if tenant else None,
        code=code,
        label=kw.pop("label", code.title()),
        category_code=kw.pop("category_code", "retail"),
        **kw,
    )
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_list_returns_system_types_plus_own(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """Verify a tenant sees system types and its own, never another tenant's."""
    await _add(db_session, test_tenant, "distributor")
    await _add(db_session, other_tenant, "franchisee")

    codes = {t.code for t in await list_user_types(db_session, test_tenant.id)}
    assert "consumer" in codes and "agent" in codes  # system
    assert "distributor" in codes  # own
    assert "franchisee" not in codes  # other tenant's


@pytest.mark.asyncio
async def test_retired_types_are_hidden_unless_requested(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify retired types leave the picker but remain resolvable."""
    await _add(db_session, test_tenant, "legacy", status="retired")

    active = {t.code for t in await list_user_types(db_session, test_tenant.id)}
    assert "legacy" not in active

    everything = {
        t.code for t in await list_user_types(db_session, test_tenant.id, include_retired=True)
    }
    assert "legacy" in everything

    assert (await get_user_type(db_session, test_tenant.id, "legacy")) is not None


@pytest.mark.asyncio
async def test_get_user_type_is_tenant_isolated(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """Verify one tenant cannot resolve another tenant's custom type."""
    await _add(db_session, other_tenant, "franchisee")
    assert (await get_user_type(db_session, test_tenant.id, "franchisee")) is None
    assert (await get_user_type(db_session, other_tenant.id, "franchisee")) is not None


@pytest.mark.asyncio
async def test_list_orders_category_sections_by_display_order(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify category sections come back in `display_order`, labels sorted within.

    Ordering by `category_code` would sort the sections alphabetically —
    business, consumer, retail. Spec §9 wants the operator-facing order, so the
    admin page can render the list without re-sorting it.
    """
    types = await list_user_types(db_session, test_tenant.id)

    sections: list[str] = []
    for t in types:
        if t.category_code not in sections:
            sections.append(t.category_code)
    assert sections == ["consumer", "retail", "business"]

    retail = [t.label for t in types if t.category_code == "retail"]
    assert retail == sorted(retail), "labels sort alphabetically within a section"
