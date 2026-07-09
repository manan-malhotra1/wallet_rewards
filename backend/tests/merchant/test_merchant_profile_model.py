"""Model tests for MerchantProfile (Epic 17 S1).

A merchant profile extends a `user_type='merchant'` user (Decision D1) with the
business + provider metadata an airtime (or future) merchant needs. These tests
lock the tenant scoping, the server-default mode/status, and the
one-active-merchant-per-service invariant the recharge flow relies on.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    MERCHANT_MODE_SIMULATOR,
    MERCHANT_PROFILE_STATUS_ACTIVE,
    USER_TYPE_MERCHANT,
    MerchantProfile,
    Tenant,
    User,
)


async def _make_merchant_user(session: AsyncSession, tenant: Tenant) -> User:
    """Persist a bare user_type='merchant' user and return it (flushed)."""
    user = User(tenant_id=tenant.id, user_type=USER_TYPE_MERCHANT)
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_merchant_profile_persists_with_server_defaults(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A profile persists and mode/status fall back to their server defaults."""
    user = await _make_merchant_user(db_session, test_tenant)
    profile = MerchantProfile(
        tenant_id=test_tenant.id,
        user_id=user.id,
        business_name="Default Airtime Merchant",
        category="airtime",
        service_code="airtime_recharge",
    )
    db_session.add(profile)
    await db_session.commit()
    await db_session.refresh(profile)

    assert profile.service_code == "airtime_recharge"
    assert profile.mode == MERCHANT_MODE_SIMULATOR
    assert profile.status == MERCHANT_PROFILE_STATUS_ACTIVE
    assert profile.provider_config == {}


@pytest.mark.asyncio
async def test_merchant_profile_is_tenant_scoped(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """A profile in one tenant is invisible when querying another tenant."""
    user = await _make_merchant_user(db_session, test_tenant)
    db_session.add(
        MerchantProfile(
            tenant_id=test_tenant.id,
            user_id=user.id,
            business_name="A",
            category="airtime",
            service_code="airtime_recharge",
        )
    )
    await db_session.commit()

    rows = (
        (
            await db_session.execute(
                select(MerchantProfile).where(MerchantProfile.tenant_id == other_tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


@pytest.mark.asyncio
async def test_only_one_active_merchant_per_service_per_tenant(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Two ACTIVE merchants serving the same service in a tenant is rejected."""
    u1 = await _make_merchant_user(db_session, test_tenant)
    u2 = await _make_merchant_user(db_session, test_tenant)
    db_session.add(
        MerchantProfile(
            tenant_id=test_tenant.id,
            user_id=u1.id,
            business_name="First",
            category="airtime",
            service_code="airtime_recharge",
        )
    )
    await db_session.commit()

    db_session.add(
        MerchantProfile(
            tenant_id=test_tenant.id,
            user_id=u2.id,
            business_name="Second",
            category="airtime",
            service_code="airtime_recharge",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
