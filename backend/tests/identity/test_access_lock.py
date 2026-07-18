"""Tests for the admin access-lock endpoint (migration 0045).

POST /api/v1/identity/users/{user_id}/access — an immediate, audited
platform-admin override that sets a user's access level (active /
login_locked / transactions_locked). login_locked kills live sessions now.
Covers level→status mapping, session kill, role-gating, tenant isolation, the
audit row, and the access_level surfaced on the user-detail payload.

Distinct from /unlock (the Redis PIN-lockout release) — that route is untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_SUSPENDED,
    USER_STATUS_TXN_LOCKED,
    AuditLog,
    Tenant,
    User,
)
from tests.conftest import create_session_token_for_user


def _access_url(user_id) -> str:
    return f"/api/v1/identity/users/{user_id}/access"


async def _reload_status(session: AsyncSession, user_id) -> str:
    """Read the user's status straight from the DB (fresh, not cached)."""
    result = await session.execute(select(User.status).where(User.id == user_id))
    return result.scalar_one()


@pytest.mark.parametrize(
    ("level", "expected_status"),
    [
        ("login_locked", USER_STATUS_SUSPENDED),
        ("transactions_locked", USER_STATUS_TXN_LOCKED),
        ("active", USER_STATUS_ACTIVE),
    ],
)
@pytest.mark.asyncio
async def test_set_access_level_flips_status(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    level: str,
    expected_status: str,
) -> None:
    """Each level maps to the right user.status and is echoed back."""
    resp = await async_client.post(
        _access_url(test_user.id),
        params={"tenant_id": str(test_tenant.id)},
        json={"level": level},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"user_id": str(test_user.id), "status": expected_status, "level": level}
    assert await _reload_status(db_session, test_user.id) == expected_status


@pytest.mark.asyncio
async def test_login_lock_kills_live_session(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """A live user session is dead immediately after the admin sets login_locked."""
    token = await create_session_token_for_user(test_user.id, test_tenant.id)
    # Session works before the lock.
    before = await async_client.get(
        "/api/v1/identity/me/wallet",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert before.status_code == 200, before.text

    resp = await async_client.post(
        _access_url(test_user.id),
        params={"tenant_id": str(test_tenant.id)},
        json={"level": "login_locked"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    # The old token is now gone → 401 invalid_session.
    after = await async_client.get(
        "/api/v1/identity/me/wallet",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert after.status_code == 401
    assert after.json()["error_code"] == "invalid_session"


@pytest.mark.asyncio
async def test_transactions_lock_does_not_kill_session(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """transactions_locked keeps the session alive — the user can still read."""
    token = await create_session_token_for_user(test_user.id, test_tenant.id)
    await async_client.post(
        _access_url(test_user.id),
        params={"tenant_id": str(test_tenant.id)},
        json={"level": "transactions_locked"},
        headers=admin_auth_header,
    )
    resp = await async_client.get(
        "/api/v1/identity/me/wallet",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_access_requires_platform_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    make_admin_token: Callable[..., str],
) -> None:
    """A token without platform-admin is forbidden (403)."""
    token = make_admin_token(roles=["support-agent"])
    resp = await async_client.post(
        _access_url(test_user.id),
        params={"tenant_id": str(test_tenant.id)},
        json={"level": "login_locked"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_access_invalid_level_is_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """An unknown level (e.g. 'closed') fails schema validation (422)."""
    resp = await async_client.post(
        _access_url(test_user.id),
        params={"tenant_id": str(test_tenant.id)},
        json={"level": "closed"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_access_unknown_user_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Unknown user_id → 404 user_not_found."""
    resp = await async_client.post(
        _access_url(uuid4()),
        params={"tenant_id": str(test_tenant.id)},
        json={"level": "login_locked"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_access_cross_tenant_404(
    async_client: AsyncClient,
    other_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Locking a user in another tenant must 404 — no existence leak."""
    resp = await async_client.post(
        _access_url(test_user.id),
        params={"tenant_id": str(other_tenant.id)},
        json={"level": "login_locked"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_access_writes_audit_row_with_before_after(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """The change is audited as admin.user_access_changed with before/after."""
    await create_session_token_for_user(test_user.id, test_tenant.id)
    await async_client.post(
        _access_url(test_user.id),
        params={"tenant_id": str(test_tenant.id)},
        json={"level": "login_locked"},
        headers=admin_auth_header,
    )
    row = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_id == str(test_user.id),
                    AuditLog.action == "admin.user_access_changed",
                )
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert row.before_state == {"status": USER_STATUS_ACTIVE}
    assert row.after_state["status"] == USER_STATUS_SUSPENDED
    assert row.after_state["sessions_killed"] == 1


@pytest.mark.asyncio
async def test_user_detail_surfaces_access_level(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """The user-detail payload derives access_level from status."""
    # Active by default.
    detail = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["access_level"] == "active"

    # After a transactions-lock the derived level flips.
    await async_client.post(
        _access_url(test_user.id),
        params={"tenant_id": str(test_tenant.id)},
        json={"level": "transactions_locked"},
        headers=admin_auth_header,
    )
    detail2 = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert detail2.json()["access_level"] == "transactions_locked"
    assert detail2.json()["status"] == USER_STATUS_TXN_LOCKED
