"""Per-service access-policy enforcement helper (`assert_service_allowed`).

Covers the pure decision logic of the server-side twin of the mobile
`/me/services` display gate: WHO (`allowed_user_types`) and HOW
(`allowed_channels`) are ANDed, NULL/empty means unrestricted, a `user_type`
of ``None`` enforces channel only, and an unconfigured service imposes no
restriction. The two rejection dimensions raise DISTINCT 403 codes so the
client can tell them apart.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.services.service import assert_service_allowed
from app.shared.exceptions import (
    ServiceNotAllowedForUserType,
    ServiceNotAllowedOnChannel,
)
from app.shared.models import Service, Tenant


async def _make_service(
    session: AsyncSession,
    tenant: Tenant,
    *,
    code: str,
    allowed_user_types: list[str] | None,
    allowed_channels: list[str] | None,
) -> Service:
    """Persist a live service with the given access policy."""
    svc = Service(
        tenant_id=tenant.id,
        code=code,
        display_name=code,
        allowed_user_types=allowed_user_types,
        allowed_channels=allowed_channels,
    )
    session.add(svc)
    await session.commit()
    return svc


@pytest.mark.asyncio
async def test_user_type_not_on_allow_list_is_rejected(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a user whose type isn't allowed for a service is refused"""
    await _make_service(
        db_session,
        test_tenant,
        code="cash_in",
        allowed_user_types=["agent", "super_agent"],
        allowed_channels=["mobile"],
    )
    with pytest.raises(ServiceNotAllowedForUserType) as exc:
        await assert_service_allowed(
            db_session,
            tenant_id=test_tenant.id,
            transaction_type="cash_in",
            user_type="consumer",
            channel="mobile",
        )
    assert exc.value.error_code == "service_not_allowed_user_type"


@pytest.mark.asyncio
async def test_user_type_on_allow_list_passes(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a user whose type is allowed for a service may use it"""
    await _make_service(
        db_session,
        test_tenant,
        code="cash_in",
        allowed_user_types=["agent", "super_agent"],
        allowed_channels=["mobile"],
    )
    # No raise == allowed.
    await assert_service_allowed(
        db_session,
        tenant_id=test_tenant.id,
        transaction_type="cash_in",
        user_type="agent",
        channel="mobile",
    )


@pytest.mark.asyncio
async def test_wrong_channel_is_rejected_with_distinct_code(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a mobile-only service cannot be initiated over the api channel"""
    await _make_service(
        db_session,
        test_tenant,
        code="p2p",
        allowed_user_types=["consumer"],
        allowed_channels=["mobile"],
    )
    with pytest.raises(ServiceNotAllowedOnChannel) as exc:
        await assert_service_allowed(
            db_session,
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            user_type="consumer",
            channel="api",
        )
    assert exc.value.error_code == "service_not_allowed_channel"


@pytest.mark.asyncio
async def test_none_user_type_skips_who_but_enforces_channel(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify an operator path with no wallet-user type is gated on channel only"""
    # A fund service confined to admin/api with an empty user-type list.
    await _make_service(
        db_session,
        test_tenant,
        code="fund",
        allowed_user_types=[],
        allowed_channels=["admin", "api"],
    )
    # user_type=None + api channel -> allowed (channel is on the list).
    await assert_service_allowed(
        db_session,
        tenant_id=test_tenant.id,
        transaction_type="fund",
        user_type=None,
        channel="api",
    )
    # A mobile-only service still rejects a None-user_type caller on channel.
    await _make_service(
        db_session,
        test_tenant,
        code="cashout",
        allowed_user_types=["consumer"],
        allowed_channels=["mobile"],
    )
    with pytest.raises(ServiceNotAllowedOnChannel):
        await assert_service_allowed(
            db_session,
            tenant_id=test_tenant.id,
            transaction_type="cashout",
            user_type=None,
            channel="api",
        )


@pytest.mark.asyncio
async def test_unconfigured_service_is_unrestricted(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a service with no catalog row imposes no access restriction"""
    # No Service row for this code at all — must not raise (NULL=all philosophy).
    await assert_service_allowed(
        db_session,
        tenant_id=test_tenant.id,
        transaction_type=f"never-configured-{uuid4().hex[:8]}",
        user_type="consumer",
        channel="api",
    )


@pytest.mark.asyncio
async def test_null_and_empty_arrays_are_unrestricted(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a service with empty/NULL policy arrays allows any user and channel"""
    await _make_service(
        db_session,
        test_tenant,
        code="open_null",
        allowed_user_types=None,
        allowed_channels=None,
    )
    await _make_service(
        db_session,
        test_tenant,
        code="open_empty",
        allowed_user_types=[],
        allowed_channels=[],
    )
    for code in ("open_null", "open_empty"):
        await assert_service_allowed(
            db_session,
            tenant_id=test_tenant.id,
            transaction_type=code,
            user_type="merchant",
            channel="ussd",
        )


@pytest.mark.asyncio
async def test_merchant_cashin_over_api_is_allowed(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a merchant may initiate merchant_cashin over the api channel"""
    await _make_service(
        db_session,
        test_tenant,
        code="merchant_cashin",
        allowed_user_types=["merchant", "head_merchant"],
        allowed_channels=["api"],
    )
    await assert_service_allowed(
        db_session,
        tenant_id=test_tenant.id,
        transaction_type="merchant_cashin",
        user_type="merchant",
        channel="api",
    )


@pytest.mark.asyncio
async def test_policy_is_tenant_scoped(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """Verify one tenant's restrictive policy never gates another tenant's caller"""
    # test_tenant restricts cash_in to agents; other_tenant has no such row.
    await _make_service(
        db_session,
        test_tenant,
        code="cash_in",
        allowed_user_types=["agent"],
        allowed_channels=["mobile"],
    )
    # A consumer in OTHER tenant is unaffected — no cash_in row there.
    await assert_service_allowed(
        db_session,
        tenant_id=other_tenant.id,
        transaction_type="cash_in",
        user_type="consumer",
        channel="mobile",
    )
