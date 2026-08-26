"""Endpoint surface: auth, tenant isolation, the checker's delta, rejects download.

Per the repo testing rules every endpoint needs a happy path, an auth failure
and a tenant-isolation check.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant
from tests.commission_batches.conftest import BatchFixture


def _csv(*lines: str) -> str:
    """A batch file with the standard header."""
    return "msisdn,currency,amount,note\n" + "".join(f"{line}\n" for line in lines)


def _header(token: str) -> dict[str, str]:
    """Bearer header for httpx."""
    return {"Authorization": f"Bearer {token}"}


async def _upload(
    client: AsyncClient, fx: BatchFixture, headers: dict[str, str], body: str
):
    """POST a disbursement batch."""
    return await client.post(
        "/api/v1/commission-batches",
        params={"tenant_id": str(fx.tenant.id)},
        headers=headers,
        data={"batch_type": "disbursement"},
        files={"file": ("nov.csv", body, "text/csv")},
    )


@pytest.mark.asyncio
async def test_upload_returns_the_validation_summary(
    async_client: AsyncClient,
    batch_fixture: BatchFixture,
    admin_auth_header: dict[str, str],
) -> None:
    """The maker sees immediately how many rows will actually pay."""
    resp = await _upload(
        async_client,
        batch_fixture,
        admin_auth_header,
        _csv(
            f"{batch_fixture.agent_msisdn},ZAR,50,Verified",
            "+27000000000,ZAR,10,Unknown",
        ),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["row_count_total"] == 2
    assert body["row_count_valid"] == 1
    assert body["status"] == "PENDING"


@pytest.mark.asyncio
async def test_upload_requires_auth(
    async_client: AsyncClient, batch_fixture: BatchFixture
) -> None:
    """No token → 401/403, never an anonymous batch."""
    resp = await _upload(
        async_client, batch_fixture, {}, _csv(f"{batch_fixture.agent_msisdn},ZAR,50,")
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_checker_view_exposes_balance_amount_and_delta(
    async_client: AsyncClient,
    batch_fixture: BatchFixture,
    admin_auth_header: dict[str, str],
) -> None:
    """The delta is the whole reason the checker screen exists (spec §8.3)."""
    created = await _upload(
        async_client,
        batch_fixture,
        admin_auth_header,
        _csv(f"{batch_fixture.agent_msisdn},ZAR,40,Held R60 pending query"),
    )
    batch_id = created.json()["id"]

    resp = await async_client.get(
        f"/api/v1/commission-batches/{batch_id}",
        params={"tenant_id": str(batch_fixture.tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    row = resp.json()["rows"][0]
    assert row["balance_snapshot"] == "100.000000"
    assert row["amount"] == "40.000000"
    # 100 accrued - 40 paid = 60 held back, justified by the note.
    assert row["delta"] == "60.000000"
    assert row["note"] == "Held R60 pending query"
    assert row["snapshot_at"] is not None


@pytest.mark.asyncio
async def test_rejects_download_is_a_csv(
    async_client: AsyncClient,
    batch_fixture: BatchFixture,
    admin_auth_header: dict[str, str],
) -> None:
    """The maker gets a re-uploadable file, not a JSON blob."""
    created = await _upload(
        async_client,
        batch_fixture,
        admin_auth_header,
        _csv(
            f"{batch_fixture.agent_msisdn},ZAR,50,",
            "+27000000000,ZAR,10,Unknown",
        ),
    )
    batch_id = created.json()["id"]

    resp = await async_client.get(
        f"/api/v1/commission-batches/{batch_id}/rejects",
        params={"tenant_id": str(batch_fixture.tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert resp.text.startswith(
        "row_number,msisdn,currency,amount,note,failure_reason"
    )
    assert "msisdn_not_found" in resp.text


@pytest.mark.asyncio
async def test_another_tenants_batch_is_not_visible(
    async_client: AsyncClient,
    batch_fixture: BatchFixture,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Tenant isolation (NFR-0220): 404, not 403 — no existence leak."""
    created = await _upload(
        async_client,
        batch_fixture,
        admin_auth_header,
        _csv(f"{batch_fixture.agent_msisdn},ZAR,50,"),
    )
    batch_id = created.json()["id"]

    resp = await async_client.get(
        f"/api/v1/commission-batches/{batch_id}",
        params={"tenant_id": str(other_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_filters_by_type(
    async_client: AsyncClient,
    batch_fixture: BatchFixture,
    admin_auth_header: dict[str, str],
) -> None:
    """The two menus each list only their own batches (D14)."""
    await _upload(
        async_client,
        batch_fixture,
        admin_auth_header,
        _csv(f"{batch_fixture.agent_msisdn},ZAR,50,"),
    )

    resp = await async_client.get(
        "/api/v1/commission-batches",
        params={"tenant_id": str(batch_fixture.tenant.id), "batch_type": "withdrawal"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    assert resp.json() == []

    resp = await async_client.get(
        "/api/v1/commission-batches",
        params={"tenant_id": str(batch_fixture.tenant.id), "batch_type": "disbursement"},
        headers=admin_auth_header,
    )
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_approve_requires_the_checker_role(
    async_client: AsyncClient,
    batch_fixture: BatchFixture,
    admin_auth_header: dict[str, str],
) -> None:
    """A platform-admin token must not be able to approve (403)."""
    created = await _upload(
        async_client,
        batch_fixture,
        admin_auth_header,
        _csv(f"{batch_fixture.agent_msisdn},ZAR,50,"),
    )
    batch_id = created.json()["id"]

    resp = await async_client.post(
        f"/api/v1/commission-batches/{batch_id}/approve",
        params={"tenant_id": str(batch_fixture.tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approve_applies_and_moves_money(
    async_client: AsyncClient,
    db_session: AsyncSession,
    batch_fixture: BatchFixture,
    admin_auth_header: dict[str, str],
    make_admin_token: Callable[..., str],
) -> None:
    """End-to-end through HTTP: upload as maker, approve as a different checker."""
    from app.modules.accounts.service import derive_balance

    created = await _upload(
        async_client,
        batch_fixture,
        admin_auth_header,
        _csv(f"{batch_fixture.agent_msisdn},ZAR,40,Verified"),
    )
    batch_id = created.json()["id"]

    checker = _header(
        make_admin_token(
            roles=["treasury-approver"], sub="77777777-7777-4000-8000-000000000007"
        )
    )
    resp = await async_client.post(
        f"/api/v1/commission-batches/{batch_id}/approve",
        params={"tenant_id": str(batch_fixture.tenant.id)},
        headers=checker,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "APPLIED"

    main_balance, _ = await derive_balance(
        db_session, batch_fixture.agent_main_wallet.id
    )
    assert main_balance == 40


@pytest.mark.asyncio
async def test_reject_requires_a_comment(
    async_client: AsyncClient,
    batch_fixture: BatchFixture,
    admin_auth_header: dict[str, str],
    make_admin_token: Callable[..., str],
) -> None:
    """An empty rejection body is a 422."""
    created = await _upload(
        async_client,
        batch_fixture,
        admin_auth_header,
        _csv(f"{batch_fixture.agent_msisdn},ZAR,40,"),
    )
    batch_id = created.json()["id"]

    checker = _header(
        make_admin_token(
            roles=["treasury-approver"], sub="88888888-8888-4000-8000-000000000008"
        )
    )
    resp = await async_client.post(
        f"/api/v1/commission-batches/{batch_id}/reject",
        params={"tenant_id": str(batch_fixture.tenant.id)},
        headers=checker,
        json={"comment": "  "},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_batch_type_is_a_422_not_a_500(
    async_client: AsyncClient,
    batch_fixture: BatchFixture,
    admin_auth_header: dict[str, str],
) -> None:
    """An unknown batch_type must be rejected by validation.

    Regression: the service indexes BATCH_OPERATION by this value, so a bare
    `str` parameter would KeyError into a 500 rather than a clean 422.
    """
    resp = await async_client.post(
        "/api/v1/commission-batches",
        params={"tenant_id": str(batch_fixture.tenant.id)},
        headers=admin_auth_header,
        data={"batch_type": "nonsense"},
        files={"file": ("nov.csv", _csv(f"{batch_fixture.agent_msisdn},ZAR,50,"), "text/csv")},
    )
    assert resp.status_code == 422
