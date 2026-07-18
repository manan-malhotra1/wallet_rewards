"""Tests for bank-mirror admin endpoints.

  - POST  /api/v1/treasury/bank-mirrors            PROPOSE a named mirror (Epic 18)
  - PATCH /api/v1/treasury/bank-mirrors/{id}       rename a mirror (direct — no money)

A bank mirror is an `operator_adjustment` account; several coexist per
(tenant, currency), each distinguished by name. Creating one now routes through
money-operation approval; renaming (which moves no money) stays a direct op.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    Account,
    Tenant,
)
from tests.treasury.conftest import approve_op


@pytest_asyncio.fixture
async def test_tenant(db_session: AsyncSession) -> Tenant:
    """Un-prefunded tenant so mirror-list assertions see ONLY test-created mirrors.

    Shadows the conftest `test_tenant` (which pre-funds the ZAR float using a
    dedicated seed bank mirror) for this module only — otherwise the seed mirror
    would leak into exact mirror-set assertions here.
    """
    tenant = Tenant(name=f"mirrors-{uuid4().hex[:8]}", business_type="both", base_currency="ZAR")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


async def _seed_bank_mirror(
    session: AsyncSession,
    tenant: Tenant,
    *,
    name: str,
    currency: str = "ZAR",
) -> Account:
    """Insert a named bank mirror (operator_adjustment) for the tenant."""
    mirror = Account(
        tenant_id=tenant.id,
        user_id=None,
        account_type=ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        currency=currency,
        name=name,
    )
    session.add(mirror)
    await session.commit()
    await session.refresh(mirror)
    return mirror


async def _propose_create(
    client: AsyncClient, tenant: Tenant, admin_auth_header: dict[str, str], *, name: str
):
    """Propose a create_bank_mirror via the treasury endpoint."""
    return await client.post(
        "/api/v1/treasury/bank-mirrors",
        headers=admin_auth_header,
        params={"tenant_id": str(tenant.id)},
        json={"currency": "ZAR", "name": name},
    )


# -----------------------------------------------------------------------------
# create (proposes, then applies on approval)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_bank_mirror_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Propose+approve creates a named operator_adjustment account."""
    proposed = await _propose_create(
        async_client, test_tenant, admin_auth_header, name="Standard Bank"
    )
    assert proposed.status_code == 201, proposed.text
    assert proposed.json()["status"] == "PENDING"

    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPLIED"

    mirror = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == test_tenant.id,
                Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
                Account.name == "Standard Bank",
            )
        )
    ).scalar_one_or_none()
    assert mirror is not None
    assert mirror.currency == "ZAR"


@pytest.mark.asyncio
async def test_create_bank_mirror_duplicate_name_returns_409_at_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """A name already used in this (tenant, currency) is rejected 409 on approval."""
    await _seed_bank_mirror(db_session, test_tenant, name="Standard Bank")
    proposed = await _propose_create(
        async_client, test_tenant, admin_auth_header, name="Standard Bank"
    )
    assert proposed.status_code == 201
    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 409
    assert approved.json()["error_code"] == "bank_mirror_name_already_exists"


@pytest.mark.asyncio
async def test_two_mirrors_with_different_names_coexist(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Two differently-named mirrors coexist for the same currency."""
    for name in ("Standard Bank", "Nedbank"):
        proposed = await _propose_create(async_client, test_tenant, admin_auth_header, name=name)
        assert proposed.status_code == 201, proposed.text
        approved = await approve_op(
            async_client, str(test_tenant.id), proposed.json()["id"], approver_header
        )
        assert approved.status_code == 200, approved.text

    mirrors = (
        (
            await db_session.execute(
                select(Account).where(
                    Account.tenant_id == test_tenant.id,
                    Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
                    Account.currency == "ZAR",
                )
            )
        )
        .scalars()
        .all()
    )
    assert {m.name for m in mirrors} == {"Standard Bank", "Nedbank"}


@pytest.mark.asyncio
async def test_create_bank_mirror_requires_auth(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Anonymous create → 401 at propose."""
    resp = await async_client.post(
        "/api/v1/treasury/bank-mirrors",
        params={"tenant_id": str(test_tenant.id)},
        json={"currency": "ZAR", "name": "X"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_bank_mirror_wrong_role_returns_403(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A token without platform-admin → 403 at propose."""
    token = make_admin_token(roles=["support-agent"])
    resp = await async_client.post(
        "/api/v1/treasury/bank-mirrors",
        headers={"Authorization": f"Bearer {token}"},
        params={"tenant_id": str(test_tenant.id)},
        json={"currency": "ZAR", "name": "X"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_bank_mirror_blank_name_returns_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """An empty name fails body validation → 422 at propose."""
    resp = await async_client.post(
        "/api/v1/treasury/bank-mirrors",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"currency": "ZAR", "name": ""},
    )
    assert resp.status_code == 422


# -----------------------------------------------------------------------------
# rename (direct — moves no money, not gated)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_bank_mirror_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Renames the mirror; the response reflects the new name."""
    mirror = await _seed_bank_mirror(db_session, test_tenant, name="Old Name")
    resp = await async_client.patch(
        f"/api/v1/treasury/bank-mirrors/{mirror.id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"name": "New Name"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_rename_bank_mirror_collision_returns_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Renaming onto an existing mirror's name in the same scope → 409."""
    await _seed_bank_mirror(db_session, test_tenant, name="Standard Bank")
    other = await _seed_bank_mirror(db_session, test_tenant, name="Nedbank")
    resp = await async_client.patch(
        f"/api/v1/treasury/bank-mirrors/{other.id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"name": "Standard Bank"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "bank_mirror_name_already_exists"


@pytest.mark.asyncio
async def test_rename_unknown_mirror_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Renaming an id that doesn't exist → 404."""
    resp = await async_client.patch(
        f"/api/v1/treasury/bank-mirrors/{uuid4()}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"name": "Whatever"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_non_operator_adjustment_account_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A non-bank-mirror system account can't be renamed via this surface."""
    inflow = Account(
        tenant_id=test_tenant.id,
        user_id=None,
        account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
        currency="ZAR",
    )
    db_session.add(inflow)
    await db_session.commit()
    await db_session.refresh(inflow)

    resp = await async_client.patch(
        f"/api/v1/treasury/bank-mirrors/{inflow.id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"name": "Nope"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_cross_tenant_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A mirror belonging to another tenant is not renamable → 404."""
    foreign = await _seed_bank_mirror(db_session, other_tenant, name="Theirs")
    resp = await async_client.patch(
        f"/api/v1/treasury/bank-mirrors/{foreign.id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"name": "Mine"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_bank_mirror_requires_auth(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> None:
    """Anonymous rename → 401."""
    mirror = await _seed_bank_mirror(db_session, test_tenant, name="Old")
    resp = await async_client.patch(
        f"/api/v1/treasury/bank-mirrors/{mirror.id}",
        params={"tenant_id": str(test_tenant.id)},
        json={"name": "New"},
    )
    assert resp.status_code == 401
