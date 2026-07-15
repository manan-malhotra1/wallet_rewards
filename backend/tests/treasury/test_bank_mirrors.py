"""Tests for bank-mirror admin endpoints (Epic 26).

  - POST  /api/v1/treasury/bank-mirrors            create a named mirror
  - PATCH /api/v1/treasury/bank-mirrors/{id}       rename a mirror

A bank mirror is an `operator_adjustment` account; several coexist per
(tenant, currency), each distinguished by name.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    Account,
    Tenant,
)


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


# -----------------------------------------------------------------------------
# create
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_bank_mirror_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Creates a named operator_adjustment account with a zero balance."""
    resp = await async_client.post(
        "/api/v1/treasury/bank-mirrors",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"currency": "ZAR", "name": "Standard Bank"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Standard Bank"
    assert body["account_type"] == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT
    assert body["currency"] == "ZAR"
    assert Decimal(body["balance"]) == Decimal("0")


@pytest.mark.asyncio
async def test_create_bank_mirror_duplicate_name_returns_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A name already used in this (tenant, currency) is rejected 409."""
    await _seed_bank_mirror(db_session, test_tenant, name="Standard Bank")
    resp = await async_client.post(
        "/api/v1/treasury/bank-mirrors",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"currency": "ZAR", "name": "Standard Bank"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "bank_mirror_name_already_exists"


@pytest.mark.asyncio
async def test_two_mirrors_with_different_names_coexist(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Two differently-named mirrors coexist for the same currency."""
    for name in ("Standard Bank", "Nedbank"):
        resp = await async_client.post(
            "/api/v1/treasury/bank-mirrors",
            headers=admin_auth_header,
            params={"tenant_id": str(test_tenant.id)},
            json={"currency": "ZAR", "name": name},
        )
        assert resp.status_code == 201, resp.text

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
    """Anonymous create → 401."""
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
    """A token without platform-admin → 403."""
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
    """An empty name fails validation → 422."""
    resp = await async_client.post(
        "/api/v1/treasury/bank-mirrors",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"currency": "ZAR", "name": ""},
    )
    assert resp.status_code == 422


# -----------------------------------------------------------------------------
# rename
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
