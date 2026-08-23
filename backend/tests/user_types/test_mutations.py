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


@pytest.mark.asyncio
async def test_reparent_cannot_smuggle_a_category_change(
    db_session: AsyncSession,
    test_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify a payload naming a different category is refused, not silently ignored.

    The bypass this closes: an update whose `category_code` says `business` and
    whose `parent_type_code` names a Business parent used to validate against the
    payload's category, pass, and then write that Business parent onto a Retail
    row — because the write block never assigns `category_code`. That is exactly
    the state `parent_type_wrong_category` exists to prevent.
    """
    await create_user_type(db_session, _req(test_tenant, "distributor"))  # retail

    with pytest.raises(AppHTTPException) as exc:
        await replace_user_type_for_scope(
            db_session,
            [
                _req(
                    test_tenant,
                    "distributor",
                    category_code="business",
                    parent_type_code="head_merchant",
                )
            ],
        )
    assert exc.value.error_code == "user_type_category_immutable"

    row = await _committed(session_factory, test_tenant.id, "distributor")
    assert row is not None
    assert row.category_code == "retail"
    assert row.parent_type_code is None, "no Business parent may land on a Retail row"


@pytest.mark.asyncio
async def test_reparent_is_validated_against_the_rows_own_category(
    db_session: AsyncSession,
    test_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify a cross-category parent is refused even with a truthful payload."""
    await create_user_type(db_session, _req(test_tenant, "distributor"))  # retail

    with pytest.raises(AppHTTPException) as exc:
        await replace_user_type_for_scope(
            db_session,
            [_req(test_tenant, "distributor", parent_type_code="head_merchant")],
        )
    assert exc.value.error_code == "parent_type_wrong_category"

    row = await _committed(session_factory, test_tenant.id, "distributor")
    assert row is not None
    assert row.parent_type_code is None


@pytest.mark.asyncio
async def test_reactivating_a_child_under_a_retired_parent_is_refused(
    db_session: AsyncSession,
    test_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify reactivation re-checks the hierarchy, not only re-parenting.

    Four steps, each individually legal, that used to compose into the state
    rule 4 forbids: create parent + child, retire the child, retire the now
    childless parent, then reactivate the child. The status-only change skipped
    the hierarchy re-check, leaving an active child under a retired parent.
    """
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

    with pytest.raises(AppHTTPException) as exc:
        await replace_user_type_for_scope(
            db_session,
            [
                _req(
                    test_tenant,
                    "sub_distributor",
                    parent_type_code="distributor",
                    status=USER_TYPE_STATUS_ACTIVE,
                )
            ],
        )
    assert exc.value.error_code == "parent_type_not_found"

    child = await _committed(session_factory, test_tenant.id, "sub_distributor")
    assert child is not None
    assert child.status == USER_TYPE_STATUS_RETIRED


@pytest.mark.asyncio
async def test_reactivation_succeeds_once_the_parent_is_active_again(
    db_session: AsyncSession,
    test_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify the reactivation guard lifts in the correct order: parent, then child."""
    await create_user_type(db_session, _req(test_tenant, "distributor"))
    await create_user_type(
        db_session, _req(test_tenant, "sub_distributor", parent_type_code="distributor")
    )
    for code in ("sub_distributor", "distributor"):
        await replace_user_type_for_scope(
            db_session,
            [
                _req(
                    test_tenant,
                    code,
                    parent_type_code="distributor" if code == "sub_distributor" else None,
                    status=USER_TYPE_STATUS_RETIRED,
                )
            ],
        )

    await replace_user_type_for_scope(
        db_session, [_req(test_tenant, "distributor", status=USER_TYPE_STATUS_ACTIVE)]
    )
    await replace_user_type_for_scope(
        db_session,
        [
            _req(
                test_tenant,
                "sub_distributor",
                parent_type_code="distributor",
                status=USER_TYPE_STATUS_ACTIVE,
            )
        ],
    )

    child = await _committed(session_factory, test_tenant.id, "sub_distributor")
    assert child is not None
    assert child.status == USER_TYPE_STATUS_ACTIVE


@pytest.mark.asyncio
async def test_duplicate_tenant_code_is_a_409_not_a_500(
    db_session: AsyncSession,
    test_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify a tenant reusing one of its OWN codes gets a clean 409 (spec §12).

    `_assert_code_available` only guards platform-wide system codes, so this
    collision reaches the `uq_user_types_tenant_code` index. Unhandled, the raw
    `IntegrityError` becomes a 500 AND poisons the session, rolling back the
    staged maker-checker approval and leaving the request stuck PENDING.
    """
    # Read off the fixture and build both payloads BEFORE the collision: the
    # `session.rollback()` inside the 409 path expires this session's identity
    # map, so touching `test_tenant.id` afterwards would trigger a lazy refresh.
    tenant_id = test_tenant.id
    duplicate = _req(test_tenant, "distributor", label="Duplicate")
    follow_up = _req(test_tenant, "franchisee")

    await create_user_type(db_session, _req(test_tenant, "distributor"))

    with pytest.raises(AppHTTPException) as exc:
        await create_user_type(db_session, duplicate)
    assert exc.value.status_code == 409
    assert exc.value.error_code == "user_type_code_already_exists"

    # The session must be usable again — the failed insert is rolled back, so
    # the original row is untouched and further work on this session succeeds.
    survivor = await _committed(session_factory, tenant_id, "distributor")
    assert survivor is not None
    assert survivor.label == "Distributor", "the losing insert must not have overwritten the label"
    await create_user_type(db_session, follow_up)
    assert await _committed(session_factory, tenant_id, "franchisee") is not None


@pytest.mark.asyncio
async def test_tenant_cannot_retire_another_tenants_type(
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify cross-tenant retire is a 404 with no existence leak (spec §12)."""
    await create_user_type(db_session, _req(other_tenant, "franchisee"))

    with pytest.raises(AppHTTPException) as exc:
        await replace_user_type_for_scope(
            db_session,
            [_req(test_tenant, "franchisee", status=USER_TYPE_STATUS_RETIRED)],
        )
    # 404 "no such user type", never the 403 that would confirm it exists
    # elsewhere, and never a distinct message for "owned by someone else".
    assert exc.value.status_code == 404
    assert exc.value.error_code == "user_type_not_found"

    victim = await _committed(session_factory, other_tenant.id, "franchisee")
    assert victim is not None
    assert victim.status == USER_TYPE_STATUS_ACTIVE


@pytest.mark.asyncio
async def test_system_type_cannot_be_retired_or_reparented(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify system immutability covers retire and reparent, not just relabel."""
    attempts = {
        "retire": _req(
            test_tenant, "agent", parent_type_code="super_agent", status=USER_TYPE_STATUS_RETIRED
        ),
        "reparent": _req(test_tenant, "agent", parent_type_code=None),
    }
    for name, payload in attempts.items():
        with pytest.raises(AppHTTPException) as exc:
            await replace_user_type_for_scope(db_session, [payload])
        assert exc.value.status_code == 403, f"{name} of a system type must be refused"
        assert exc.value.error_code == "user_type_is_system"
