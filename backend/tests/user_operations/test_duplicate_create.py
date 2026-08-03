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
from tests.user_operations.conftest import (
    create_user_payload,
    ops_url,
    propose,
    request_changes,
)


def _phone_payload(phone: str) -> dict:
    """A minimal valid create_user payload carrying exactly one phone identifier."""
    return {
        "identifiers": [{"identifier_type": "phone", "identifier_value": phone}],
        "user_type": "consumer",
    }


async def _seed_user_with_phone(
    session: AsyncSession, tenant: Tenant, canonical_phone: str
) -> None:
    """Insert a live user owning `canonical_phone` (already-normalised form)."""
    user = User(tenant_id=tenant.id)
    session.add(user)
    await session.flush()
    session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=tenant.id,
            identifier_type="phone",
            identifier_value=canonical_phone,
            verified=True,
        )
    )
    await session.commit()


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
    await _seed_user_with_phone(db_session, test_tenant, "+27825559999")

    # Propose using a VISUALLY different but same-canonical phone (spaces) — the
    # guard must normalise to match, so this still collides.
    resp = await _propose_raw(
        async_client, test_tenant, maker_header, _phone_payload("+27 82 555 9999")
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "identifier_already_in_use"


@pytest.mark.asyncio
async def test_propose_create_no_plus_collides_with_live_plus_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify a phone WITHOUT '+' is blocked when the same number exists WITH '+' (reported bug)"""
    # A live user owns the canonical '+'-prefixed form.
    await _seed_user_with_phone(db_session, test_tenant, "+27825550007")

    # The admin re-enters the SAME real number without the leading '+'. This is
    # the exact case that slipped through before phone normalisation added the '+'.
    resp = await _propose_raw(
        async_client, test_tenant, maker_header, _phone_payload("27825550007")
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "identifier_already_in_use"


@pytest.mark.asyncio
async def test_propose_create_twice_no_plus_vs_plus_409(
    async_client: AsyncClient,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify a second pending proposal WITHOUT '+' collides with a first WITH '+' (reported bug)"""
    # First proposal lands PENDING with the '+'-prefixed form.
    first = await propose(
        async_client, test_tenant, maker_header, "create_user", _phone_payload("+27825550007")
    )
    assert first["status"] == "PENDING"

    # Second proposal for the SAME number without the '+' must be rejected — the
    # two pending proposals the UI let through are now collapsed to one identifier.
    resp = await _propose_raw(
        async_client, test_tenant, maker_header, _phone_payload("27825550007")
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


@pytest.mark.asyncio
async def test_revise_create_to_taken_identifier_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify revising a create_user proposal onto a taken phone is rejected (the second door)"""
    # A live user already owns this canonical phone.
    await _seed_user_with_phone(db_session, test_tenant, "+27825552222")

    # A create_user proposal on a FRESH phone reaches CHANGES_REQUESTED.
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", _phone_payload("+27 82 555 3333")
    )
    cr = await request_changes(
        async_client, test_tenant, proposed["id"], checker_header, "Use a different number."
    )
    assert cr.json()["status"] == "CHANGES_REQUESTED"

    # Revising onto the taken phone must be rejected exactly like propose.
    resp = await async_client.patch(
        ops_url(test_tenant, f"/{proposed['id']}"),
        content=json.dumps({"payload": _phone_payload("+27825552222")}),
        headers=maker_header,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "identifier_already_in_use"


@pytest.mark.asyncio
async def test_propose_create_same_identifier_other_tenant_succeeds(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify a phone used in another tenant does NOT block a create_user here (tenant-scoped)"""
    # The SAME canonical phone exists as a live user — but in a DIFFERENT tenant.
    await _seed_user_with_phone(db_session, other_tenant, "+27825554444")

    body = await propose(
        async_client, test_tenant, maker_header, "create_user", _phone_payload("+27 82 555 4444")
    )
    assert body["status"] == "PENDING"


@pytest.mark.asyncio
async def test_propose_create_multi_identifier_one_taken_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify a create_user with two identifiers is rejected when ONE already belongs to a user"""
    await _seed_user_with_phone(db_session, test_tenant, "+27825555555")

    # Payload carries a fresh email PLUS the already-taken phone.
    payload = {
        "identifiers": [
            {"identifier_type": "email", "identifier_value": "fresh-user@example.com"},
            {"identifier_type": "phone", "identifier_value": "+27 82 555 5555"},
        ],
        "user_type": "consumer",
    }
    resp = await _propose_raw(async_client, test_tenant, maker_header, payload)
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error_code"] == "identifier_already_in_use"
    # Only the phone collides, so the phone is the identifier named in the message.
    assert "phone" in body["message"]
