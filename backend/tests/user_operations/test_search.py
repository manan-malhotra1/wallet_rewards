"""Server-side search over the user-operations queue (B7.2c).

Mirrors the money-operations search contract: `q` filters the list and
/counts endpoints across the whole queue (request id, maker, payload text).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, User, UserProfile
from tests.user_operations.conftest import create_user_payload, ops_url, propose


@pytest.mark.asyncio
async def test_q_matches_payload_text(
    async_client: AsyncClient, test_tenant: Tenant, maker_header: dict[str, str]
) -> None:
    """Verify q matches a value inside the payload (the new user's first name)."""
    wanted = create_user_payload()
    wanted["profile"]["first_name"] = "Zanele"
    other = create_user_payload()
    proposed = await propose(async_client, test_tenant, maker_header, "create_user", wanted)
    await propose(async_client, test_tenant, maker_header, "create_user", other)

    resp = await async_client.get(ops_url(test_tenant) + "&q=zanele", headers=maker_header)
    assert resp.status_code == 200
    assert [op["id"] for op in resp.json()] == [proposed["id"]]


@pytest.mark.asyncio
async def test_q_with_no_match_returns_empty(
    async_client: AsyncClient, test_tenant: Tenant, maker_header: dict[str, str]
) -> None:
    """Verify an unmatched q yields an empty list, not an error."""
    await propose(async_client, test_tenant, maker_header, "create_user", create_user_payload())
    resp = await async_client.get(
        ops_url(test_tenant) + "&q=zzz-no-such-thing", headers=maker_header
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_q_matches_target_display_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
) -> None:
    """Verify q matches the edited user's PROFILE name.

    An update_user payload carries only the target's UUID (this one edits just
    the status), but the UI shows the resolved display name — so a checker
    searches by name and must hit.
    """
    db_session.add(UserProfile(user_id=test_user.id, first_name="Sipho", last_name="Ncube"))
    await db_session.commit()
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "update_user",
        {"target_user_id": str(test_user.id), "status": "active"},
    )
    await propose(async_client, test_tenant, maker_header, "create_user", create_user_payload())

    resp = await async_client.get(ops_url(test_tenant) + "&q=sipho", headers=maker_header)
    assert resp.status_code == 200
    assert [op["id"] for op in resp.json()] == [proposed["id"]]


@pytest.mark.asyncio
async def test_counts_apply_q(
    async_client: AsyncClient, test_tenant: Tenant, maker_header: dict[str, str]
) -> None:
    """Verify /counts filters by q, so a searching page's pager stays correct."""
    wanted = create_user_payload()
    wanted["profile"]["first_name"] = "Thandiwe"
    await propose(async_client, test_tenant, maker_header, "create_user", wanted)
    await propose(async_client, test_tenant, maker_header, "create_user", create_user_payload())

    resp = await async_client.get(
        ops_url(test_tenant, "/counts") + "&q=thandiwe", headers=maker_header
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
