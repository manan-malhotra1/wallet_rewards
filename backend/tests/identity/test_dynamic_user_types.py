"""Identity tests for dynamic user types and the type-driven parent rule.

Covers the two hardcoded structures retired by the configurable-user-types
feature (spec §5/§6): `PARENT_TYPE_BY_CHILD`, replaced by the child type row's
`parent_type_code`, and the dropped `ck_users_user_type` CHECK, replaced by a
service-level `unknown_user_type` refusal on every path that writes a type.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal
from app.modules.identity.schemas import ChangeUserTypeRequest, CreateUserRequest, IdentifierIn
from app.modules.identity.service import admin_update_user, change_user_type, create_user
from app.modules.user_types.schemas import UserTypeCreateRequest
from app.modules.user_types.service import create_user_type
from app.shared.exceptions import AppHTTPException
from app.shared.models import Role, Tenant

_ADMIN = AdminPrincipal(
    id="00000000-0000-4000-8000-0000000000ad", username="admin", roles=frozenset()
)


async def _custom_type(
    session: AsyncSession,
    tenant: Tenant,
    code: str,
    *,
    parent_type_code: str | None = None,
    status: str = "active",
) -> None:
    """Create a tenant-scoped custom user type for the test.

    Args:
        session: Async DB session.
        tenant: Owning tenant.
        code: The type code.
        parent_type_code: Declared supervisor type, or None for a top-level type.
        status: 'active' or 'retired'.
    """
    await create_user_type(
        session,
        UserTypeCreateRequest(
            tenant_id=tenant.id,
            code=code,
            label=code.replace("_", " ").capitalize(),
            category_code="retail",
            parent_type_code=parent_type_code,
            status=status,
        ),
    )


async def _user(session: AsyncSession, tenant: Tenant, phone: str, user_type: str, **kw: object):
    """Create a user of `user_type` identified by `phone`."""
    return await create_user(
        session,
        CreateUserRequest(
            tenant_id=tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value=phone)],
            user_type=user_type,
            **kw,  # type: ignore[arg-type]
        ),
    )


@pytest.mark.asyncio
async def test_user_can_be_created_with_a_custom_type(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify a user takes a tenant-created type — the whole point of the feature."""
    await _custom_type(db_session, test_tenant, "distributor")

    user = await _user(db_session, test_tenant, "+27825551234", "distributor")
    assert user.user_type == "distributor"


@pytest.mark.asyncio
async def test_unknown_type_is_refused(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify the service-level check replaces the dropped CHECK constraint."""
    with pytest.raises(AppHTTPException) as exc:
        await _user(db_session, test_tenant, "+27825559999", "not_a_real_type")
    assert exc.value.error_code == "unknown_user_type"


@pytest.mark.asyncio
async def test_retired_type_is_refused_for_a_new_user(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify a retired type still resolves but can no longer be assigned (spec §6)."""
    await _custom_type(db_session, test_tenant, "legacy_agent", status="retired")

    with pytest.raises(AppHTTPException) as exc:
        await _user(db_session, test_tenant, "+27825559998", "legacy_agent")
    assert exc.value.error_code == "unknown_user_type"


@pytest.mark.asyncio
async def test_another_tenants_type_is_refused(
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    default_user_role: Role,
) -> None:
    """Verify type visibility is tenant-scoped — no borrowing another tenant's type."""
    await _custom_type(db_session, other_tenant, "franchisee")

    with pytest.raises(AppHTTPException) as exc:
        await _user(db_session, test_tenant, "+27825559997", "franchisee")
    assert exc.value.error_code == "unknown_user_type"


@pytest.mark.asyncio
async def test_parent_type_comes_from_the_type_row(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify a custom child type enforces its own declared parent type."""
    await _custom_type(db_session, test_tenant, "distributor")
    await _custom_type(db_session, test_tenant, "sub_distributor", parent_type_code="distributor")

    boss = await _user(db_session, test_tenant, "+27825550001", "distributor")
    child = await _user(
        db_session, test_tenant, "+27825550002", "sub_distributor", parent_user_id=boss.id
    )
    assert child.parent_user_id == boss.id

    # A consumer cannot supervise a sub_distributor.
    wrong = await _user(db_session, test_tenant, "+27825550003", "consumer")
    with pytest.raises(AppHTTPException):
        await _user(
            db_session, test_tenant, "+27825550004", "sub_distributor", parent_user_id=wrong.id
        )


@pytest.mark.asyncio
async def test_change_user_type_refuses_an_unknown_type(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify the type check also guards the admin type-change path."""
    user = await _user(db_session, test_tenant, "+27825550010", "consumer")

    with pytest.raises(AppHTTPException) as exc:
        await change_user_type(
            db_session,
            user_id=user.id,
            tenant_id=test_tenant.id,
            request=ChangeUserTypeRequest(new_type="not_a_real_type", reason="testing"),
            admin=_ADMIN,
        )
    assert exc.value.error_code == "unknown_user_type"


@pytest.mark.asyncio
async def test_admin_update_refuses_an_unknown_type(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify the maker-checker user-edit path cannot write a bogus type either."""
    user = await _user(db_session, test_tenant, "+27825550011", "consumer")

    with pytest.raises(AppHTTPException) as exc:
        await admin_update_user(
            db_session,
            user_id=user.id,
            tenant_id=test_tenant.id,
            user_type="not_a_real_type",
            admin=_ADMIN,
        )
    assert exc.value.error_code == "unknown_user_type"


@pytest.mark.asyncio
async def test_merchant_binding_follows_the_business_category(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify Business-category membership, not a flag, gates a merchant API key.

    Replaces the `requires_merchant_profile` boolean that this test previously
    encoded: the column is gone, and merchant capability is now derived from
    `category_code == CATEGORY_BUSINESS`, exactly as cash-out eligibility is
    derived from the Retail category. A tenant's own Business type therefore
    qualifies the moment it is created, with no second flag to remember.
    """
    from app.modules.api_keys.schemas import ApiKeyCreateRequest
    from app.modules.api_keys.service import create_api_key

    await create_user_type(
        db_session,
        UserTypeCreateRequest(
            tenant_id=test_tenant.id,
            code="franchise_store",
            label="Franchise store",
            category_code="business",
        ),
    )
    await create_user_type(
        db_session,
        UserTypeCreateRequest(
            tenant_id=test_tenant.id,
            code="kiosk",
            label="Kiosk",
            category_code="retail",
        ),
    )
    store = await _user(db_session, test_tenant, "+27825550020", "franchise_store")
    plain = await _user(db_session, test_tenant, "+27825550021", "consumer")
    kiosk = await _user(db_session, test_tenant, "+27825550022", "kiosk")

    key, _secret = await create_api_key(
        db_session,
        ApiKeyCreateRequest(tenant_id=test_tenant.id, merchant_user_id=store.id),
        admin=_ADMIN,
    )
    assert key.merchant_user_id == store.id

    # Consumers and Retail sit outside the Business category, so neither may
    # carry a merchant-bound key however the type was created.
    for outsider in (plain, kiosk):
        with pytest.raises(AppHTTPException) as exc:
            await create_api_key(
                db_session,
                ApiKeyCreateRequest(tenant_id=test_tenant.id, merchant_user_id=outsider.id),
                admin=_ADMIN,
            )
        assert exc.value.error_code == "merchant_user_required"
