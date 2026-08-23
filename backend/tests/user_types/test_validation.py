"""Validation tests for the four hierarchy rules and code collisions (spec §5)."""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.service import assert_type_definition_valid
from app.shared.exceptions import AppHTTPException
from app.shared.models import Tenant, UserTypeDef


async def _add(session: AsyncSession, tenant: Tenant, code: str, **kw: Any) -> UserTypeDef:
    """Insert one tenant-scoped type row for a test.

    Args:
        session: Async DB session.
        tenant: Owning tenant.
        code: The type code to insert.
        **kw: Column overrides — `category_code` defaults to retail.

    Returns:
        The flushed `UserTypeDef` row.
    """
    row = UserTypeDef(
        tenant_id=tenant.id,
        code=code,
        label=code.title(),
        category_code=kw.pop("category_code", "retail"),
        **kw,
    )
    session.add(row)
    await session.flush()
    return row


async def _err(session: AsyncSession, tenant: Tenant, **kw: Any) -> str:
    """Call the validator and return the error_code it raises.

    Args:
        session: Async DB session.
        tenant: The tenant proposing the type.
        **kw: Keyword arguments forwarded to `assert_type_definition_valid`.

    Returns:
        The `error_code` carried by the raised `AppHTTPException`.
    """
    with pytest.raises(AppHTTPException) as exc:
        await assert_type_definition_valid(session, tenant_id=tenant.id, **kw)
    return str(exc.value.error_code)


@pytest.mark.asyncio
async def test_valid_child_under_toplevel_parent_passes(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a child under an active same-category top-level parent is accepted."""
    await assert_type_definition_valid(
        db_session,
        tenant_id=test_tenant.id,
        code="junior_agent",
        category_code="retail",
        parent_type_code="super_agent",
    )


@pytest.mark.asyncio
async def test_parent_must_be_toplevel(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify the two-level cap: a child cannot hang under another child."""
    assert (
        await _err(
            db_session,
            test_tenant,
            code="sub_agent",
            category_code="retail",
            parent_type_code="agent",  # agent is itself a child
        )
        == "parent_type_not_toplevel"
    )


@pytest.mark.asyncio
async def test_parent_must_share_category(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a Retail child cannot hang under a Business parent."""
    assert (
        await _err(
            db_session,
            test_tenant,
            code="odd",
            category_code="retail",
            parent_type_code="head_merchant",
        )
        == "parent_type_wrong_category"
    )


@pytest.mark.asyncio
async def test_flat_category_rejects_a_parent(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify Consumers stays flat."""
    assert (
        await _err(
            db_session,
            test_tenant,
            code="vip",
            category_code="consumer",
            parent_type_code="consumer",
        )
        == "category_does_not_support_hierarchy"
    )


@pytest.mark.asyncio
async def test_unknown_parent_is_rejected(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a parent that does not resolve for this tenant is refused."""
    assert (
        await _err(
            db_session,
            test_tenant,
            code="x",
            category_code="retail",
            parent_type_code="does_not_exist",
        )
        == "parent_type_not_found"
    )


@pytest.mark.asyncio
async def test_retired_parent_is_rejected(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a new child cannot be attached to a retired parent."""
    await _add(db_session, test_tenant, "old_boss", status="retired")
    assert (
        await _err(
            db_session,
            test_tenant,
            code="y",
            category_code="retail",
            parent_type_code="old_boss",
        )
        == "parent_type_not_found"
    )


@pytest.mark.asyncio
async def test_system_code_is_reserved(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a tenant cannot shadow a system type code."""
    assert (
        await _err(
            db_session,
            test_tenant,
            code="agent",
            category_code="retail",
        )
        == "user_type_code_reserved"
    )


@pytest.mark.asyncio
async def test_unknown_category_points_at_the_category_field(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a nonexistent category reports itself, not a bad user type.

    This used to raise `unknown_user_type` ("That user type is not available for
    this tenant"), sending the operator to inspect the type field when the
    category is what does not exist.
    """
    assert (
        await _err(
            db_session,
            test_tenant,
            code="diaspora_sender",
            category_code="nonexistent",
        )
        == "unknown_user_type_category"
    )
