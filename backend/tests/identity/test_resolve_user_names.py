"""Unit tests for `identity.service.resolve_user_names`.

Covers the display-name resolution order: profile full name first, primary
identifier value as a fallback, and omission (caller falls back to a short id)
when a user has neither. Tenant scoping is asserted too (NFR-0220).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.service import resolve_user_names
from app.shared.models import Tenant, User, UserIdentifier, UserProfile


async def _make_user(
    db_session: AsyncSession,
    tenant: Tenant,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    identifiers: list[tuple[str, str]] | None = None,
) -> User:
    """Create a bare user with an optional profile + identifiers for a test."""
    user = User(tenant_id=tenant.id)
    db_session.add(user)
    await db_session.flush()
    if first_name is not None or last_name is not None:
        db_session.add(
            UserProfile(user_id=user.id, first_name=first_name, last_name=last_name)
        )
    for id_type, id_value in identifiers or []:
        db_session.add(
            UserIdentifier(
                user_id=user.id,
                tenant_id=tenant.id,
                identifier_type=id_type,
                identifier_value=id_value,
                verified=True,
            )
        )
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_resolves_to_profile_full_name(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A user with a profile resolves to the joined + stripped full name."""
    user = await _make_user(
        db_session,
        test_tenant,
        first_name="Jane",
        last_name="Doe",
        identifiers=[("phone", "+27825550101")],
    )
    names = await resolve_user_names(
        db_session, tenant_id=test_tenant.id, user_ids=[user.id]
    )
    assert names[user.id] == "Jane Doe"


@pytest.mark.asyncio
async def test_partial_profile_uses_available_name_part(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A profile with only a first name resolves to just that (no stray space)."""
    user = await _make_user(db_session, test_tenant, first_name="Jane")
    names = await resolve_user_names(
        db_session, tenant_id=test_tenant.id, user_ids=[user.id]
    )
    assert names[user.id] == "Jane"


@pytest.mark.asyncio
async def test_falls_back_to_identifier_when_no_profile(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """No profile → the primary identifier value stands in for the name."""
    user = await _make_user(
        db_session, test_tenant, identifiers=[("phone", "+27825550202")]
    )
    names = await resolve_user_names(
        db_session, tenant_id=test_tenant.id, user_ids=[user.id]
    )
    assert names[user.id] == "+27825550202"


@pytest.mark.asyncio
async def test_identifier_fallback_prefers_phone_over_email(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """When several identifiers exist, phone wins over email."""
    user = await _make_user(
        db_session,
        test_tenant,
        identifiers=[("email", "jane@example.com"), ("phone", "+27825550303")],
    )
    names = await resolve_user_names(
        db_session, tenant_id=test_tenant.id, user_ids=[user.id]
    )
    assert names[user.id] == "+27825550303"


@pytest.mark.asyncio
async def test_omitted_when_no_profile_and_no_identifier(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A user with neither a profile nor an identifier is absent from the map."""
    user = await _make_user(db_session, test_tenant)
    names = await resolve_user_names(
        db_session, tenant_id=test_tenant.id, user_ids=[user.id]
    )
    assert user.id not in names


@pytest.mark.asyncio
async def test_unknown_user_id_is_omitted(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A user id that does not exist simply does not appear in the result."""
    names = await resolve_user_names(
        db_session, tenant_id=test_tenant.id, user_ids=[uuid4()]
    )
    assert names == {}


@pytest.mark.asyncio
async def test_tenant_scoped_does_not_resolve_other_tenant_user(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """A user in another tenant never resolves, even by id (NFR-0220)."""
    user = await _make_user(
        db_session,
        other_tenant,
        first_name="Cross",
        last_name="Tenant",
        identifiers=[("phone", "+27825550404")],
    )
    names = await resolve_user_names(
        db_session, tenant_id=test_tenant.id, user_ids=[user.id]
    )
    assert names == {}


@pytest.mark.asyncio
async def test_batches_mixed_users(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """One call resolves profile-named, identifier-only, and nameless users."""
    named = await _make_user(db_session, test_tenant, first_name="Amara", last_name="N")
    ident_only = await _make_user(
        db_session, test_tenant, identifiers=[("phone", "+27825550505")]
    )
    nameless = await _make_user(db_session, test_tenant)

    names = await resolve_user_names(
        db_session,
        tenant_id=test_tenant.id,
        user_ids=[named.id, ident_only.id, nameless.id],
    )
    assert names[named.id] == "Amara N"
    assert names[ident_only.id] == "+27825550505"
    assert nameless.id not in names
