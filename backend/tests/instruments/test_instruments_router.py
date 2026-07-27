"""Currency catalog management.

Covers list (tenant-scoped + status filter), create (happy + dup-code +
auth + validation), patch (display_name + status + 404), soft-delete
(idempotent re-create after delete), and the assign_to_existing_users
backfill side-effect.
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Account, Instrument, Tenant, User


async def _seed_instrument(
    session: AsyncSession,
    tenant_id: str,
    code: str,
    symbol: str = "?",
    display_name: str | None = None,
    account_type: str = "financial_wallet",
    status: str = "active",
) -> Instrument:
    """Insert an instrument row directly so individual tests don't depend on POST."""
    inst = Instrument(
        tenant_id=tenant_id,
        code=code,
        symbol=symbol,
        display_name=display_name or code,
        account_type=account_type,
        status=status,
    )
    session.add(inst)
    await session.commit()
    await session.refresh(inst)
    return inst


@pytest.mark.asyncio
async def test_list_instruments_requires_auth(
    async_client: AsyncClient, test_tenant: Tenant
) -> None:
    """Verify the currency catalog cannot be listed without signing in"""
    resp = await async_client.get("/api/v1/instruments", params={"tenant_id": str(test_tenant.id)})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_instruments_returns_active_and_disabled(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the currency catalog lists both active and disabled currencies"""
    await _seed_instrument(db_session, str(test_tenant.id), "ZAR", "R")
    await _seed_instrument(db_session, str(test_tenant.id), "BTC", "₿", status="disabled")
    resp = await async_client.get(
        "/api/v1/instruments",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    codes = {i["code"] for i in resp.json()}
    assert codes == {"ZAR", "BTC"}


@pytest.mark.asyncio
async def test_list_instruments_status_filter(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the currency catalog can be filtered to active currencies"""
    await _seed_instrument(db_session, str(test_tenant.id), "ZAR", "R")
    await _seed_instrument(db_session, str(test_tenant.id), "OLD", "x", status="disabled")
    resp = await async_client.get(
        "/api/v1/instruments",
        params={"tenant_id": str(test_tenant.id), "status": "active"},
        headers=admin_auth_header,
    )
    codes = [i["code"] for i in resp.json()]
    assert codes == ["ZAR"]


@pytest.mark.asyncio
async def test_list_instruments_tenant_isolated(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify one tenant's currency catalog does not show another tenant's currencies"""
    await _seed_instrument(db_session, str(test_tenant.id), "ZAR", "R")
    await _seed_instrument(db_session, str(other_tenant.id), "ZAR", "R")
    resp = await async_client.get(
        "/api/v1/instruments",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    body = resp.json()
    assert len(body) == 1
    assert body[0]["tenant_id"] == str(test_tenant.id)


@pytest.mark.asyncio
async def test_create_instrument_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a new currency can be added to the catalog"""
    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "USDC",
            "symbol": "$",
            "display_name": "USD Coin",
            "account_type": "financial_wallet",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "USDC"
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_create_instrument_duplicate_code_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a currency code cannot be added twice in a tenant"""
    await _seed_instrument(db_session, str(test_tenant.id), "ZAR", "R")
    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "ZAR",
            "symbol": "R",
            "display_name": "Duplicate",
            "account_type": "financial_wallet",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "instrument_code_already_exists"


@pytest.mark.asyncio
async def test_create_instrument_rejects_lowercase_code(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a currency code must be uppercase"""
    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "zar",
            "symbol": "R",
            "display_name": "Bad case",
            "account_type": "financial_wallet",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_instrument_with_backfill_creates_user_accounts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify adding a currency can give every existing customer an account for it"""
    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "USDC",
            "symbol": "$",
            "display_name": "USD Coin",
            "account_type": "financial_wallet",
            "assign_to_existing_users": True,
        },
    )
    assert resp.status_code == 201, resp.text

    # Verify the user got a USDC financial_wallet account.
    accounts = (
        (
            await db_session.execute(
                select(Account).where(
                    Account.tenant_id == test_tenant.id,
                    Account.user_id == test_user.id,
                    Account.currency == "USDC",
                    Account.account_type == "financial_wallet",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(accounts) == 1


@pytest.mark.asyncio
async def test_create_instrument_without_backfill_skips_user_accounts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify adding a currency leaves existing customers without an account unless requested"""
    await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "USDC",
            "symbol": "$",
            "display_name": "USD Coin",
            "account_type": "financial_wallet",
        },
    )
    accounts = (
        (
            await db_session.execute(
                select(Account).where(
                    Account.tenant_id == test_tenant.id,
                    Account.user_id == test_user.id,
                    Account.currency == "USDC",
                )
            )
        )
        .scalars()
        .all()
    )
    assert accounts == []


@pytest.mark.asyncio
async def test_patch_instrument_display_name_and_status(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a currency's name, symbol, and status can be edited"""
    inst = await _seed_instrument(db_session, str(test_tenant.id), "PTS", "p", "Points")
    resp = await async_client.patch(
        f"/api/v1/instruments/{inst.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"symbol": "Rewards", "display_name": "Rewards Points", "status": "disabled"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["symbol"] == "Rewards"
    assert body["display_name"] == "Rewards Points"
    assert body["status"] == "disabled"
    assert body["code"] == "PTS"
    assert body["account_type"] == "financial_wallet"


@pytest.mark.asyncio
async def test_patch_rejects_code_field(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a currency's code cannot be changed after creation"""
    inst = await _seed_instrument(db_session, str(test_tenant.id), "ZAR", "R")
    resp = await async_client.patch(
        f"/api/v1/instruments/{inst.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"code": "RENAMED"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_unknown_instrument_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify editing an unknown currency is rejected"""
    resp = await async_client.patch(
        f"/api/v1/instruments/{uuid4()}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"symbol": "x"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_instrument_removes_from_list(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a removed currency no longer appears in the catalog"""
    inst = await _seed_instrument(db_session, str(test_tenant.id), "ZAR", "R")
    delete_resp = await async_client.delete(
        f"/api/v1/instruments/{inst.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert delete_resp.status_code == 200

    list_resp = await async_client.get(
        "/api/v1/instruments",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert list_resp.status_code == 200
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_delete_then_recreate_same_code_succeeds(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a removed currency code can be added again"""
    inst = await _seed_instrument(db_session, str(test_tenant.id), "ZAR", "R")
    await async_client.delete(
        f"/api/v1/instruments/{inst.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    create_resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "ZAR",
            "symbol": "R",
            "display_name": "Reborn",
            "account_type": "financial_wallet",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
