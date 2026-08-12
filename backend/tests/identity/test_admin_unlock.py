"""Admin unlock — releasing a customer locked out by wrong PIN attempts.

Covers POST /api/v1/identity/users/{id}/unlock (release a lockout without a PIN
change), the fix that admin PIN-reset now ALSO clears an active lockout, and the
is_locked / unlocks_in_seconds fields on the user-detail payload.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.lockout import clear_lockout, is_locked, register_failure
from app.config import settings
from app.shared.models import AuditLog, Tenant, User


async def _lock(user_id) -> None:
    """Drive the user into the locked state via the failure counter."""
    for _ in range(settings.PIN_MAX_ATTEMPTS):
        await register_failure(user_id)


@pytest.fixture(autouse=True)
async def _clean_lock(test_user: User):
    """Ensure no lock leaks across tests (Redis is shared, keys are per-user)."""
    yield
    await clear_lockout(test_user.id)


@pytest.mark.asyncio
async def test_unlock_releases_a_locked_user(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can release a customer locked out by wrong PIN attempts"""
    await _lock(test_user.id)
    assert await is_locked(test_user.id) is True

    resp = await async_client.post(
        f"/api/v1/identity/users/{test_user.id}/unlock",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"user_id": str(test_user.id), "was_locked": True}
    assert await is_locked(test_user.id) is False


@pytest.mark.asyncio
async def test_unlock_when_not_locked_is_a_noop(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify unlocking a customer who is not locked simply succeeds"""
    resp = await async_client.post(
        f"/api/v1/identity/users/{test_user.id}/unlock",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["was_locked"] is False


@pytest.mark.asyncio
async def test_unlock_requires_platform_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify only a platform administrator can unlock a customer"""
    token = make_admin_token(roles=["support-agent"])
    resp = await async_client.post(
        f"/api/v1/identity/users/{test_user.id}/unlock",
        params={"tenant_id": str(test_tenant.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unlock_unknown_user_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify unlocking a customer who does not exist is rejected"""
    resp = await async_client.post(
        f"/api/v1/identity/users/{uuid4()}/unlock",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_unlock_cross_tenant_returns_404(
    async_client: AsyncClient,
    other_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin cannot unlock a customer in another tenant"""
    resp = await async_client.post(
        f"/api/v1/identity/users/{test_user.id}/unlock",
        params={"tenant_id": str(other_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unlock_writes_audit_row(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify unlocking a customer is recorded in the audit trail"""
    await _lock(test_user.id)
    await async_client.post(
        f"/api/v1/identity/users/{test_user.id}/unlock",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    row = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_id == str(test_user.id),
                    AuditLog.action == "admin.user_unlocked",
                )
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert row.after_state == {"was_locked": True}


@pytest.mark.asyncio
async def test_admin_pin_reset_also_clears_an_active_lockout(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify resetting a customer's PIN also releases an active lockout"""
    await _lock(test_user.id)
    assert await is_locked(test_user.id) is True

    resp = await async_client.post(
        f"/api/v1/identity/users/{test_user.id}/pin/reset",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert await is_locked(test_user.id) is False


@pytest.mark.asyncio
async def test_user_detail_surfaces_lock_status(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a customer's lockout status and remaining time show on their profile"""
    # Unlocked first.
    unlocked = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["is_locked"] is False
    assert unlocked.json()["unlocks_in_seconds"] is None

    # Now locked.
    await _lock(test_user.id)
    locked = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    body = locked.json()
    assert body["is_locked"] is True
    assert body["unlocks_in_seconds"] is not None and body["unlocks_in_seconds"] > 0
