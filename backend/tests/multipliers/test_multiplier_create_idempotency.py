"""Idempotency + bound tests for POST /api/v1/multipliers (Pay-PRD-0200).

Every state-mutating endpoint requires an `Idempotency-Key` header; a replay
with the same key must return the ORIGINAL multiplier without inserting a
second row. The factor is also capped at 999.99 (the Numeric(5,2) column
bound) so an oversized value is a 422, not a DB-level 500.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import BonusMultiplier, Tenant


def _idem_headers(admin_auth_header: dict[str, str], key: str) -> dict[str, str]:
    """Admin auth headers + the given Idempotency-Key."""
    return {**admin_auth_header, "Idempotency-Key": key}


async def _count_multipliers(db_session: AsyncSession, tenant_id) -> int:
    """Number of bonus_multipliers rows in the tenant."""
    return (
        await db_session.execute(
            select(func.count())
            .select_from(BonusMultiplier)
            .where(BonusMultiplier.tenant_id == tenant_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_create_multiplier_without_idempotency_key_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a bonus multiplier cannot be created without an Idempotency-Key"""
    resp = await async_client.post(
        "/api/v1/multipliers",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "multiplier": "2.00"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_idempotency_key_returns_original_multiplier(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a replayed create returns the original bonus without a duplicate row"""
    key = f"idem-{uuid4().hex}"
    payload = {"tenant_id": str(test_tenant.id), "multiplier": "2.50"}

    first = await async_client.post(
        "/api/v1/multipliers",
        headers=_idem_headers(admin_auth_header, key),
        json=payload,
    )
    assert first.status_code == 201, first.text

    replay = await async_client.post(
        "/api/v1/multipliers",
        headers=_idem_headers(admin_auth_header, key),
        json=payload,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert await _count_multipliers(db_session, test_tenant.id) == 1


@pytest.mark.asyncio
async def test_distinct_idempotency_keys_create_distinct_multipliers(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a fresh Idempotency-Key still creates a brand-new bonus"""
    payload = {"tenant_id": str(test_tenant.id), "multiplier": "3.00"}
    a = await async_client.post(
        "/api/v1/multipliers",
        headers=_idem_headers(admin_auth_header, f"idem-{uuid4().hex}"),
        json=payload,
    )
    b = await async_client.post(
        "/api/v1/multipliers",
        headers=_idem_headers(admin_auth_header, f"idem-{uuid4().hex}"),
        json=payload,
    )
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]
    assert await _count_multipliers(db_session, test_tenant.id) == 2


@pytest.mark.asyncio
async def test_same_idempotency_key_in_other_tenant_is_independent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify idempotency keys are scoped per business, not global"""
    key = f"idem-{uuid4().hex}"
    a = await async_client.post(
        "/api/v1/multipliers",
        headers=_idem_headers(admin_auth_header, key),
        json={"tenant_id": str(test_tenant.id), "multiplier": "2.00"},
    )
    b = await async_client.post(
        "/api/v1/multipliers",
        headers=_idem_headers(admin_auth_header, key),
        json={"tenant_id": str(other_tenant.id), "multiplier": "2.00"},
    )
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]


@pytest.mark.asyncio
async def test_oversized_multiplier_rejected_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a bonus factor larger than 999.99 is rejected up front"""
    resp = await async_client.post(
        "/api/v1/multipliers",
        headers=_idem_headers(admin_auth_header, f"idem-{uuid4().hex}"),
        json={"tenant_id": str(test_tenant.id), "multiplier": "1000"},
    )
    assert resp.status_code == 422
