"""api_keys model tests (Epic 14 S1).

Covers persistence + defaults, the global uniqueness of the public key_id,
and tenant scoping of the rows.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import ApiKey, Tenant


@pytest.mark.asyncio
async def test_api_key_persists_with_active_default(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A new key persists, defaults to status 'active', and starts unused."""
    key = ApiKey(
        tenant_id=test_tenant.id,
        key_id="sak_persist_1",
        secret_encrypted="enc-token",
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    assert key.id is not None
    assert key.status == "active"
    assert key.last_used_at is None


@pytest.mark.asyncio
async def test_api_key_key_id_is_globally_unique(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """key_id is the public lookup handle in the auth path — it must be unique
    across the whole table (tenant is derived FROM the key, not vice versa)."""
    db_session.add(ApiKey(tenant_id=test_tenant.id, key_id="sak_dup", secret_encrypted="e1"))
    await db_session.commit()
    db_session.add(ApiKey(tenant_id=test_tenant.id, key_id="sak_dup", secret_encrypted="e2"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_api_keys_are_tenant_scoped(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """Rows carry tenant_id so admin listing can be scoped to one tenant."""
    db_session.add(ApiKey(tenant_id=test_tenant.id, key_id="sak_a", secret_encrypted="e"))
    db_session.add(ApiKey(tenant_id=other_tenant.id, key_id="sak_b", secret_encrypted="e"))
    await db_session.commit()
    rows = (
        (await db_session.execute(select(ApiKey).where(ApiKey.tenant_id == other_tenant.id)))
        .scalars()
        .all()
    )
    assert [r.key_id for r in rows] == ["sak_b"]
