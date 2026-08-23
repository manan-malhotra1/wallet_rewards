"""A supervisor proposed at user creation must survive the approval (spec §7.4).

The admin "Register user" dialog does not call `POST /identity/users` — it
proposes a `create_user` operation that a second admin approves later. The
supervisor therefore has to travel in the maker-checker payload and be applied
at approve time; a payload field that is accepted at propose time and silently
dropped at apply time is worse than no field at all, because commission would
then flow to nobody while the operator believes it is attached.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.schemas import CreateUserRequest, IdentifierIn
from app.modules.identity.service import create_user
from app.shared.models import Role, Tenant, User
from tests.user_operations.conftest import approve, create_user_payload, propose


async def _super_agent(session: AsyncSession, tenant: Tenant, phone: str) -> User:
    """Create the supervisor the proposal will name by phone.

    Args:
        session: Async DB session.
        tenant: Owning tenant.
        phone: The phone identifier the proposal looks the supervisor up by.

    Returns:
        The created super agent.
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
async def test_supervisor_survives_approval(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    default_user_role: Role,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify a supervisor named in the proposal is attached to the created user"""
    boss = await _super_agent(db_session, test_tenant, "+27825553000")
    payload = create_user_payload(user_type="agent")
    payload["parent_identifier"] = {
        "identifier_type": "phone",
        "identifier_value": "+27825553000",
    }

    proposed = await propose(async_client, test_tenant, maker_header, "create_user", payload)
    resp = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert resp.status_code == 200, resp.text
    created_id = resp.json()["applied_user_id"]

    created = await db_session.get(User, created_id)
    assert created is not None
    assert created.parent_user_id == boss.id


@pytest.mark.asyncio
async def test_supervisor_is_optional(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    default_user_role: Role,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify omitting the supervisor still creates the user with no parent"""
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "create_user",
        create_user_payload(user_type="agent"),
    )
    resp = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert resp.status_code == 200, resp.text

    created = await db_session.get(User, resp.json()["applied_user_id"])
    assert created is not None
    assert created.parent_user_id is None


@pytest.mark.asyncio
async def test_supervisor_of_the_wrong_type_is_refused_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    default_user_role: Role,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify the supervisor is RE-validated at approve time, not just proposed

    The identifier travels rather than an id precisely so the hierarchy rule is
    re-checked when the change actually lands — a proposal can sit in the queue
    long enough for the named person to change type.
    """
    consumer = await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=test_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825553100")],
            user_type="consumer",
        ),
    )
    assert consumer.user_type == "consumer"

    payload = create_user_payload(user_type="agent")
    payload["parent_identifier"] = {
        "identifier_type": "phone",
        "identifier_value": "+27825553100",
    }
    proposed = await propose(async_client, test_tenant, maker_header, "create_user", payload)

    resp = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert resp.status_code == 422, resp.text
