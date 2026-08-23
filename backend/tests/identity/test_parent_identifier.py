"""Tests for attaching a supervisor by identifier at onboarding (spec §7).

The supervisor is optional everywhere — these tests pin that down alongside the
two failure modes the identifier form introduces: an ambiguous double reference,
and a cross-tenant identifier that must look exactly like a missing one.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.schemas import CreateUserRequest, IdentifierIn, ParentIdentifierIn
from app.modules.identity.service import create_user
from app.shared.exceptions import AppHTTPException
from app.shared.models import Role, Tenant, User


async def _super_agent(session: AsyncSession, tenant: Tenant, phone: str) -> User:
    """Create a super-agent to act as the supervisor.

    Args:
        session: Async DB session.
        tenant: Owning tenant.
        phone: The phone identifier the supervisor is later looked up by.

    Returns:
        The created supervisor.
    """
    return await create_user(
        session,
        CreateUserRequest(
            tenant_id=tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value=phone)],
            user_type="super_agent",
        ),
    )


@pytest.mark.asyncio
async def test_agent_without_a_supervisor_succeeds(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify the supervisor is genuinely optional — the common case."""
    agent = await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=test_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825551000")],
            user_type="agent",
        ),
    )
    assert agent.parent_user_id is None


@pytest.mark.asyncio
async def test_supervisor_attaches_by_phone(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify parent_identifier resolves and attaches."""
    boss = await _super_agent(db_session, test_tenant, "+27825552000")
    agent = await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=test_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825552001")],
            user_type="agent",
            parent_identifier=ParentIdentifierIn(
                identifier_type="phone", identifier_value="+27825552000"
            ),
        ),
    )
    assert agent.parent_user_id == boss.id


@pytest.mark.asyncio
async def test_supervisor_identifier_is_normalised_before_lookup(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify a differently-formatted phone still resolves the same supervisor."""
    boss = await _super_agent(db_session, test_tenant, "+27825552100")
    agent = await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=test_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825552101")],
            user_type="agent",
            parent_identifier=ParentIdentifierIn(
                identifier_type="phone", identifier_value="+27 82 555 2100"
            ),
        ),
    )
    assert agent.parent_user_id == boss.id


@pytest.mark.asyncio
async def test_both_parent_forms_is_ambiguous(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify parent_user_id and parent_identifier are mutually exclusive."""
    boss = await _super_agent(db_session, test_tenant, "+27825553000")
    with pytest.raises(AppHTTPException) as exc:
        await create_user(
            db_session,
            CreateUserRequest(
                tenant_id=test_tenant.id,
                identifiers=[
                    IdentifierIn(identifier_type="phone", identifier_value="+27825553001")
                ],
                user_type="agent",
                parent_user_id=boss.id,
                parent_identifier=ParentIdentifierIn(
                    identifier_type="phone", identifier_value="+27825553000"
                ),
            ),
        )
    assert exc.value.error_code == "parent_reference_ambiguous"


@pytest.mark.asyncio
async def test_unknown_supervisor_identifier_is_refused(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify an identifier nobody holds is a clean 422, not a 500."""
    with pytest.raises(AppHTTPException) as exc:
        await create_user(
            db_session,
            CreateUserRequest(
                tenant_id=test_tenant.id,
                identifiers=[
                    IdentifierIn(identifier_type="phone", identifier_value="+27825553500")
                ],
                user_type="agent",
                parent_identifier=ParentIdentifierIn(
                    identifier_type="phone", identifier_value="+27825553501"
                ),
            ),
        )
    assert exc.value.error_code == "parent_not_found"


@pytest.mark.asyncio
async def test_cross_tenant_supervisor_is_not_found(
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    default_user_role: Role,
    default_user_role_other_tenant: Role,
) -> None:
    """Verify a supervisor in another tenant looks identical to a missing one."""
    await _super_agent(db_session, other_tenant, "+27825554000")
    with pytest.raises(AppHTTPException) as exc:
        await create_user(
            db_session,
            CreateUserRequest(
                tenant_id=test_tenant.id,
                identifiers=[
                    IdentifierIn(identifier_type="phone", identifier_value="+27825554001")
                ],
                user_type="agent",
                parent_identifier=ParentIdentifierIn(
                    identifier_type="phone", identifier_value="+27825554000"
                ),
            ),
        )
    assert exc.value.error_code == "parent_not_found"


@pytest.mark.asyncio
async def test_resolved_supervisor_still_faces_the_type_check(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role: Role
) -> None:
    """Verify resolving by identifier does not bypass the parent-type rule."""
    await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=test_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825555000")],
            user_type="consumer",
        ),
    )
    with pytest.raises(AppHTTPException) as exc:
        await create_user(
            db_session,
            CreateUserRequest(
                tenant_id=test_tenant.id,
                identifiers=[
                    IdentifierIn(identifier_type="phone", identifier_value="+27825555001")
                ],
                user_type="agent",
                parent_identifier=ParentIdentifierIn(
                    identifier_type="phone", identifier_value="+27825555000"
                ),
            ),
        )
    assert exc.value.error_code == "user_type_invalid_parent"
