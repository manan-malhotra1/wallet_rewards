"""Mutation tests — create, relabel, retire, and the active-children guard.

Every persistence assertion reads back through a SEPARATE session opened from
`session_factory`. Both mutations commit, and only an independent session proves
that: re-reading through the writing session would pass off the identity map
even if nothing had reached the database.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.user_types.schemas import UserTypeCreateRequest
from app.modules.user_types.service import (
    create_user_type,
    get_user_type,
    replace_user_type_for_scope,
)
from app.shared.exceptions import AppHTTPException
from app.shared.models import (
    USER_TYPE_STATUS_ACTIVE,
    USER_TYPE_STATUS_RETIRED,
    Tenant,
    UserTypeDef,
)


def _req(tenant: Tenant, code: str, **kw: Any) -> UserTypeCreateRequest:
    """Build a create request with sensible defaults.

    Args:
        tenant: The tenant that owns the proposed type.
        code: The type code.
        **kw: Field overrides — `label` defaults to the title-cased code and
            `category_code` to retail.

    Returns:
        A validated `UserTypeCreateRequest`.
    """
    return UserTypeCreateRequest(
        tenant_id=tenant.id,
        code=code,
        label=kw.pop("label", code.title()),
        category_code=kw.pop("category_code", "retail"),
        **kw,
    )


async def _committed(
    factory: async_sessionmaker[AsyncSession], tenant_id: UUID, code: str
) -> UserTypeDef | None:
    """Read one type back through a fresh session, seeing only committed rows.

    Args:
        factory: The test session factory, bound to the same test database.
        tenant_id: The owning tenant.
        code: The type code to resolve.

    Returns:
        The persisted row, or None if the write never reached the database.
    """
    async with factory() as other:
        return await get_user_type(other, tenant_id, code)


@pytest.mark.asyncio
async def test_create_then_relabel(
    db_session: AsyncSession,
    test_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify a type is created, then relabelled in place with its code intact.

    Both steps must be committed: an approved config request that only flushed
    would silently not persist.
    """
    created = await create_user_type(db_session, _req(test_tenant, "distributor"))
    assert created.code == "distributor"
    assert created.is_system is False
    original_id = created.id

    persisted = await _committed(session_factory, test_tenant.id, "distributor")
    assert persisted is not None, "create_user_type must commit"
    assert persisted.id == original_id

    await replace_user_type_for_scope(
        db_session, [_req(test_tenant, "distributor", label="Master Distributor")]
    )

    relabelled = await _committed(session_factory, test_tenant.id, "distributor")
    assert relabelled is not None, "replace_user_type_for_scope must commit"
    assert relabelled.label == "Master Distributor"
    assert relabelled.code == "distributor"  # code is immutable
    # The row must be updated IN PLACE — a delete+insert would mint a new id and
    # lose created_at for a record downstream tables reference by code (spec D3).
    assert relabelled.id == original_id


@pytest.mark.asyncio
async def test_retire_is_blocked_by_active_children(
    db_session: AsyncSession,
    test_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify a parent with active children cannot be retired, and stays active."""
    await create_user_type(db_session, _req(test_tenant, "distributor"))
    await create_user_type(
        db_session, _req(test_tenant, "sub_distributor", parent_type_code="distributor")
    )

    with pytest.raises(AppHTTPException) as exc:
        await replace_user_type_for_scope(
            db_session,
            [_req(test_tenant, "distributor", status=USER_TYPE_STATUS_RETIRED)],
        )
    assert exc.value.error_code == "user_type_has_active_children"

    # The refusal must leave nothing behind: the guard raises before the row is
    # touched, so no partial retire can have been committed.
    parent = await _committed(session_factory, test_tenant.id, "distributor")
    assert parent is not None
    assert parent.status == USER_TYPE_STATUS_ACTIVE


@pytest.mark.asyncio
async def test_retire_succeeds_once_children_are_retired(
    db_session: AsyncSession,
    test_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify the guard lifts after the children are retired, and both retires stick."""
    await create_user_type(db_session, _req(test_tenant, "distributor"))
    await create_user_type(
        db_session, _req(test_tenant, "sub_distributor", parent_type_code="distributor")
    )
    await replace_user_type_for_scope(
        db_session,
        [
            _req(
                test_tenant,
                "sub_distributor",
                parent_type_code="distributor",
                status=USER_TYPE_STATUS_RETIRED,
            )
        ],
    )
    await replace_user_type_for_scope(
        db_session, [_req(test_tenant, "distributor", status=USER_TYPE_STATUS_RETIRED)]
    )

    for code in ("sub_distributor", "distributor"):
        row = await _committed(session_factory, test_tenant.id, code)
        assert row is not None, f"{code} must still resolve once retired (spec §11)"
        assert row.status == USER_TYPE_STATUS_RETIRED


@pytest.mark.asyncio
async def test_system_type_cannot_be_modified(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify system types are immutable."""
    with pytest.raises(AppHTTPException) as exc:
        await replace_user_type_for_scope(db_session, [_req(test_tenant, "agent", label="Renamed")])
    assert exc.value.status_code == 403
