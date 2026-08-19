"""Server-side search over the money-operations queue (B7.2c).

The approvals toolbar's search used to run client-side over a fully fetched
queue; with B7.1 windows it could only see one page, so a matching request
outside the window looked nonexistent. `q` now filters server-side — across
the WHOLE queue — on both the list and the /counts endpoints.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, User, UserProfile
from tests.money_operations.conftest import ops_url, propose, user_phone


async def _propose_named_mirrors(
    client: AsyncClient, tenant: Tenant, maker_header: dict[str, str], names: list[str]
) -> list[str]:
    """Propose one create_bank_mirror per name; return ids in propose order."""
    ids: list[str] = []
    for name in names:
        proposed = await propose(
            client, tenant, maker_header, "create_bank_mirror", {"currency": "ZAR", "name": name}
        )
        ids.append(proposed["id"])
    return ids


@pytest.mark.asyncio
async def test_q_matches_payload_text(
    async_client: AsyncClient, test_tenant: Tenant, maker_header: dict[str, str]
) -> None:
    """Verify q matches a value stored inside the payload (the mirror's name)."""
    ids = await _propose_named_mirrors(
        async_client, test_tenant, maker_header, ["alpha-mirror", "beta-mirror"]
    )
    resp = await async_client.get(ops_url(test_tenant) + "&q=alpha", headers=maker_header)
    assert resp.status_code == 200
    assert [op["id"] for op in resp.json()] == [ids[0]]


@pytest.mark.asyncio
async def test_q_matches_partial_request_id(
    async_client: AsyncClient, test_tenant: Tenant, maker_header: dict[str, str]
) -> None:
    """Verify q matches a partial request id, case-insensitively."""
    ids = await _propose_named_mirrors(async_client, test_tenant, maker_header, ["a", "b"])
    fragment = ids[0][:13]
    resp = await async_client.get(
        ops_url(test_tenant) + f"&q={fragment.upper()}", headers=maker_header
    )
    assert resp.status_code == 200
    assert [op["id"] for op in resp.json()] == [ids[0]]


@pytest.mark.asyncio
async def test_q_composes_with_status_filter(
    async_client: AsyncClient, test_tenant: Tenant, maker_header: dict[str, str]
) -> None:
    """Verify q and status_filter apply together."""
    ids = await _propose_named_mirrors(
        async_client, test_tenant, maker_header, ["gamma-keep", "gamma-drop"]
    )
    resp = await async_client.post(
        ops_url(test_tenant, f"/{ids[1]}/withdraw"), headers=maker_header
    )
    assert resp.status_code == 200

    resp = await async_client.get(
        ops_url(test_tenant) + "&q=gamma&status_filter=PENDING", headers=maker_header
    )
    assert resp.status_code == 200
    assert [op["id"] for op in resp.json()] == [ids[0]]


@pytest.mark.asyncio
async def test_q_with_no_match_returns_empty(
    async_client: AsyncClient, test_tenant: Tenant, maker_header: dict[str, str]
) -> None:
    """Verify an unmatched q yields an empty list, not an error."""
    await _propose_named_mirrors(async_client, test_tenant, maker_header, ["delta"])
    resp = await async_client.get(
        ops_url(test_tenant) + "&q=zzz-no-such-thing", headers=maker_header
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_q_matches_subject_display_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
) -> None:
    """Verify q matches the funded user's PROFILE name.

    The payload stores only the identifier (a phone number), but the UI shows
    the resolved display name — so a checker searches by name and must hit.
    """
    db_session.add(UserProfile(user_id=test_user.id, first_name="Nomvula", last_name="Dlamini"))
    await db_session.commit()
    # The payload keeps whatever the maker TYPED — often a spaced phone —
    # while user_identifiers stores the normalised compact form. The name
    # search must bridge that formatting gap (it bit on live data).
    phone = user_phone(test_user)
    spaced_phone = f"{phone[:3]} {phone[3:5]} {phone[5:]}"
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "fund_user",
        {
            "identifier_type": "phone",
            "identifier_value": spaced_phone,
            "amount": "10",
            "currency": "ZAR",
        },
    )
    await propose(
        async_client, test_tenant, maker_header, "create_bank_mirror",
        {"currency": "ZAR", "name": "unrelated"},
    )

    resp = await async_client.get(ops_url(test_tenant) + "&q=nomvula", headers=maker_header)
    assert resp.status_code == 200
    assert [op["id"] for op in resp.json()] == [proposed["id"]]


@pytest.mark.asyncio
async def test_counts_apply_q(
    async_client: AsyncClient, test_tenant: Tenant, maker_header: dict[str, str]
) -> None:
    """Verify /counts filters by q, so a searching page's pager stays correct."""
    await _propose_named_mirrors(
        async_client, test_tenant, maker_header, ["epsilon-one", "epsilon-two", "other"]
    )
    resp = await async_client.get(
        ops_url(test_tenant, "/counts") + "&q=epsilon", headers=maker_header
    )
    assert resp.status_code == 200
    counts = resp.json()
    assert counts["total"] == 2
    assert counts["by_status"]["PENDING"] == 2
