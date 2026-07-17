"""Shared fixtures + helpers for user-operation maker-checker tests.

Provides maker / checker / second-checker auth headers with distinct Keycloak
subs (N-eyes needs distinct actors), payload builders, and small counters used
to assert "nothing changed" on propose.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant, User

# Distinct Keycloak subs — N-eyes requires distinct approvers.
MAKER_SUB = "11111111-1111-4000-8000-000000000001"
CHECKER_SUB = "22222222-2222-4000-8000-000000000002"
CHECKER2_SUB = "33333333-3333-4000-8000-000000000003"


def _header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def maker_header(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """A platform-admin maker (proposes; may revise/resubmit/withdraw)."""
    return _header(make_admin_token(roles=["platform-admin"], sub=MAKER_SUB))


@pytest.fixture
def checker_header(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """A user-approver checker, distinct from the maker."""
    return _header(make_admin_token(roles=["user-approver"], sub=CHECKER_SUB))


@pytest.fixture
def checker2_header(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """A SECOND distinct user-approver (for six-eyes / duplicate tests)."""
    return _header(make_admin_token(roles=["user-approver"], sub=CHECKER2_SUB))


@pytest.fixture
def maker_who_can_approve(make_admin_token: Callable[..., str]) -> dict[str, str]:
    """Same sub as the maker but also holds user-approver (self-approval test)."""
    return _header(make_admin_token(roles=["platform-admin", "user-approver"], sub=MAKER_SUB))


def ops_url(tenant: Tenant, suffix: str = "") -> str:
    """User-operations endpoint URL with the tenant_id query param."""
    return f"/api/v1/user-operations{suffix}?tenant_id={tenant.id}"


def create_user_payload(*, user_type: str = "consumer") -> dict:
    """A valid create_user payload with a unique phone + email."""
    token = uuid4().hex[:8]
    phone = f"+27 82 555 {uuid4().int % 10000:04d}"
    return {
        "identifiers": [
            {"identifier_type": "phone", "identifier_value": phone},
            {"identifier_type": "email", "identifier_value": f"user-{token}@example.com"},
        ],
        "user_type": user_type,
        "profile": {"first_name": "Ada", "last_name": "Lovelace"},
    }


async def propose(
    client: AsyncClient,
    tenant: Tenant,
    maker_header: dict[str, str],
    operation: str,
    payload: dict,
) -> dict:
    """Propose a user operation via the API and return the response JSON."""
    resp = await client.post(
        ops_url(tenant),
        content=json.dumps({"operation": operation, "payload": payload}),
        headers=maker_header,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def approve(client: AsyncClient, tenant: Tenant, op_id: str, checker_header: dict[str, str]):
    """Approve a user operation via the API."""
    return await client.post(ops_url(tenant, f"/{op_id}/approve"), headers=checker_header)


async def request_changes(
    client: AsyncClient, tenant: Tenant, op_id: str, checker_header: dict[str, str], comment: str
):
    """Request changes on a user operation via the API."""
    return await client.post(
        ops_url(tenant, f"/{op_id}/request-changes"),
        content=json.dumps({"comment": comment}),
        headers={**checker_header, "Content-Type": "application/json"},
    )


async def user_count(session: AsyncSession, tenant: Tenant) -> int:
    """Number of users in the tenant."""
    return (
        await session.execute(
            select(func.count()).select_from(User).where(User.tenant_id == tenant.id)
        )
    ).scalar_one()
