"""A create_user proposal must be unique at propose time (not just at apply).

Guards the maker-checker duplicate-create bug: an admin could stack two PENDING
`create_user` proposals for the SAME phone, or propose one for an identifier a
live user already owns — the collision only surfaced at apply. Propose now
rejects both with 409 `identifier_already_in_use`.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, User, UserIdentifier
from tests.user_operations.conftest import create_user_payload, ops_url, propose


def _phone_payload(phone: str) -> dict:
    """A minimal valid create_user payload carrying exactly one phone identifier."""
    return {
        "identifiers": [{"identifier_type": "phone", "identifier_value": phone}],
        "user_type": "consumer",
    }


async def _propose_raw(
    client: AsyncClient, tenant: Tenant, header: dict[str, str], payload: dict
) -> object:
    """Propose a create_user op without asserting success (returns the response)."""
    return await client.post(
        ops_url(tenant),
        content=json.dumps({"operation": "create_user", "payload": payload}),
        headers=header,
    )


@pytest.mark.asyncio
async def test_propose_create_for_existing_user_identifier_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify you cannot propose to create a user with a phone a live user already has"""
    # A live user owning the CANONICAL phone form (as create_user would store it).
    user = User(tenant_id=test_tenant.id)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=test_tenant.id,
            identifier_type="phone",
            identifier_value="+27825559999",
            verified=True,
        )
    )
    await db_session.commit()

    # Propose using a VISUALLY different but same-canonical phone (spaces) — the
    # guard must normalise to match, so this still collides.
    resp = await _propose_raw(
        async_client, test_tenant, maker_header, _phone_payload("+27 82 555 9999")
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "identifier_already_in_use"


@pytest.mark.asyncio
async def test_propose_create_twice_same_identifier_409(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify a second pending proposal for the same new phone is rejected (the reported bug)"""
    payload = _phone_payload("+27 82 555 1000")

    # First proposal lands PENDING.
    first = await propose(async_client, test_tenant, maker_header, "create_user", payload)
    assert first["status"] == "PENDING"

    # Second proposal for the SAME phone (differently spaced) is rejected.
    resp = await _propose_raw(
        async_client, test_tenant, maker_header, _phone_payload("+27825551000")
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "identifier_already_in_use"


@pytest.mark.asyncio
async def test_propose_create_fresh_identifier_succeeds(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify proposing to create a user with an unused phone still succeeds (regression guard)"""
    body = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    assert body["status"] == "PENDING"


@pytest.mark.asyncio
async def test_propose_second_create_different_identifier_succeeds(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify a second proposal for a DIFFERENT phone is unaffected (guard isn't over-broad)"""
    first = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    assert first["status"] == "PENDING"
    second = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    assert second["status"] == "PENDING"
