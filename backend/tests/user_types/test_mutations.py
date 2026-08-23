"""Mutation tests — create, relabel, retire, and the active-children guard."""

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.user_types.schemas import UserTypeCreateRequest
from app.modules.user_types.service import create_user_type, replace_user_type_for_scope
from app.shared.exceptions import AppHTTPException
from app.shared.models import USER_TYPE_STATUS_RETIRED, Tenant


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


@pytest.mark.asyncio
async def test_create_then_relabel(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a type is created, then relabelled in place with its code intact."""
    created = await create_user_type(db_session, _req(test_tenant, "distributor"))
    assert created.code == "distributor"
    assert created.is_system is False
    original_id = created.id

    await replace_user_type_for_scope(
        db_session, [_req(test_tenant, "distributor", label="Master Distributor")]
    )
    await db_session.refresh(created)
    assert created.label == "Master Distributor"
    assert created.code == "distributor"  # code is immutable
    # The row must be updated IN PLACE — a delete+insert would mint a new id and
    # lose created_at for a record downstream tables reference by code (spec D3).
    assert created.id == original_id


@pytest.mark.asyncio
async def test_retire_is_blocked_by_active_children(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a parent with active children cannot be retired."""
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


@pytest.mark.asyncio
async def test_retire_succeeds_once_children_are_retired(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the guard lifts after the children are retired."""
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


@pytest.mark.asyncio
async def test_system_type_cannot_be_modified(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify system types are immutable."""
    with pytest.raises(AppHTTPException) as exc:
        await replace_user_type_for_scope(db_session, [_req(test_tenant, "agent", label="Renamed")])
    assert exc.value.status_code == 403
