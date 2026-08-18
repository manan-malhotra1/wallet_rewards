"""`resolve_service_code` — the shared money-path service-code resolver.

Covers spec §7 (resolution algorithm) and the resolution-time side of §6.2
(narrowing intersection): the effective access policy for a derived service
is the INTERSECTION of the base's CURRENT allow-lists and the derived row's
own, so a base narrowed AFTER a derived service was saved still tightens it
immediately rather than letting the derived service outlive the restriction.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.services.service import resolve_service_code
from app.shared.exceptions import (
    AppHTTPException,
    ServiceNotAllowedOnChannel,
    ServiceNotFound,
)
from app.shared.models import Service, Tenant


async def _seed_base(
    session: AsyncSession,
    tenant: Tenant,
    code: str,
    *,
    allowed_channels: list[str] | None = None,
    allowed_user_types: list[str] | None = None,
) -> Service:
    """Persist a live base service, matching the Task 4 test fixture shape."""
    row = Service(
        tenant_id=tenant.id,
        code=code,
        display_name=code.replace("_", " ").title(),
        kind="base",
        status="active",
        allowed_channels=allowed_channels,
        allowed_user_types=allowed_user_types,
    )
    session.add(row)
    await session.commit()
    return row


async def _seed_derived(
    session: AsyncSession,
    tenant: Tenant,
    code: str,
    base_service_code: str,
    *,
    status: str = "active",
    allowed_channels: list[str] | None = None,
    allowed_user_types: list[str] | None = None,
) -> Service:
    """Persist a live derived service pointing at `base_service_code`."""
    row = Service(
        tenant_id=tenant.id,
        code=code,
        display_name=code.replace("_", " ").title(),
        kind="derived",
        base_service_code=base_service_code,
        status=status,
        allowed_channels=allowed_channels,
        allowed_user_types=allowed_user_types,
    )
    session.add(row)
    await session.commit()
    return row


@pytest.mark.asyncio
async def test_omitted_service_code_returns_the_base_code_unchanged(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify no `service_code` supplied resolves to the endpoint's own base"""
    await _seed_base(db_session, test_tenant, "p2p")

    resolved = await resolve_service_code(
        db_session,
        tenant_id=test_tenant.id,
        base_code="p2p",
        requested_code=None,
    )
    assert resolved == "p2p"


@pytest.mark.asyncio
async def test_explicit_base_code_resolves_to_itself(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify explicitly requesting the base code is legal and returns it"""
    await _seed_base(db_session, test_tenant, "p2p")

    resolved = await resolve_service_code(
        db_session,
        tenant_id=test_tenant.id,
        base_code="p2p",
        requested_code="p2p",
    )
    assert resolved == "p2p"


@pytest.mark.asyncio
async def test_derived_code_whose_base_matches_resolves_to_the_derived_code(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a derived service pointed at THIS endpoint's base resolves"""
    await _seed_base(db_session, test_tenant, "p2p")
    await _seed_derived(db_session, test_tenant, "p2p_diaspora", "p2p")

    resolved = await resolve_service_code(
        db_session,
        tenant_id=test_tenant.id,
        base_code="p2p",
        requested_code="p2p_diaspora",
    )
    assert resolved == "p2p_diaspora"


@pytest.mark.asyncio
async def test_derived_code_whose_base_does_not_match_is_rejected(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a cash-out derivative cannot be driven through the P2P endpoint"""
    await _seed_base(db_session, test_tenant, "cashout")
    await _seed_derived(db_session, test_tenant, "cashout_atm", "cashout")

    with pytest.raises(AppHTTPException) as exc:
        await resolve_service_code(
            db_session,
            tenant_id=test_tenant.id,
            base_code="p2p",
            requested_code="cashout_atm",
        )
    assert exc.value.status_code == 422
    assert exc.value.error_code == "service_code_mismatch"


@pytest.mark.asyncio
async def test_unknown_code_is_not_found(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a code with no live row anywhere in the tenant 404s"""
    with pytest.raises(ServiceNotFound):
        await resolve_service_code(
            db_session,
            tenant_id=test_tenant.id,
            base_code="p2p",
            requested_code="does_not_exist",
        )


@pytest.mark.asyncio
async def test_disabled_derived_service_is_rejected(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a disabled derived service cannot be resolved"""
    await _seed_base(db_session, test_tenant, "p2p")
    await _seed_derived(db_session, test_tenant, "p2p_diaspora", "p2p", status="disabled")

    with pytest.raises(AppHTTPException) as exc:
        await resolve_service_code(
            db_session,
            tenant_id=test_tenant.id,
            base_code="p2p",
            requested_code="p2p_diaspora",
        )
    assert exc.value.status_code == 409
    assert exc.value.error_code == "service_disabled"


@pytest.mark.asyncio
async def test_cross_tenant_code_is_not_found(
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
) -> None:
    """Verify a code that only exists in another tenant 404s, never leaks"""
    await _seed_base(db_session, other_tenant, "p2p")
    await _seed_derived(db_session, other_tenant, "p2p_diaspora", "p2p")

    with pytest.raises(ServiceNotFound):
        await resolve_service_code(
            db_session,
            tenant_id=test_tenant.id,
            base_code="p2p",
            requested_code="p2p_diaspora",
        )


@pytest.mark.asyncio
async def test_resolution_time_intersection_blocks_a_channel_the_base_now_excludes(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the base's CURRENT channel policy is enforced, not the derived
    row's save-time snapshot.

    Base allows [web, mobile]; the derived service was saved allowing only
    [web] (narrower-or-equal at save time). Resolving for `mobile` must still
    be rejected — the derived row was never allowed on `mobile` to begin
    with — while resolving for `web` succeeds.
    """
    await _seed_base(db_session, test_tenant, "p2p", allowed_channels=["web", "mobile"])
    await _seed_derived(db_session, test_tenant, "p2p_diaspora", "p2p", allowed_channels=["web"])

    with pytest.raises(ServiceNotAllowedOnChannel):
        await resolve_service_code(
            db_session,
            tenant_id=test_tenant.id,
            base_code="p2p",
            requested_code="p2p_diaspora",
            channel="mobile",
        )

    resolved = await resolve_service_code(
        db_session,
        tenant_id=test_tenant.id,
        base_code="p2p",
        requested_code="p2p_diaspora",
        channel="web",
    )
    assert resolved == "p2p_diaspora"


@pytest.mark.asyncio
async def test_resolution_time_intersection_tightens_when_base_is_narrowed_later(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a base narrowed AFTER the derived service was saved is enforced
    immediately (spec §6.2 belt-and-braces), not just at the next save.

    The derived row still carries its original (once-valid) [web, mobile]
    allow-list, but the base has since been narrowed to [web] only. The
    INTERSECTION — not the derived row's stale snapshot — must govern.
    """
    base = await _seed_base(db_session, test_tenant, "p2p", allowed_channels=["web", "mobile"])
    await _seed_derived(
        db_session,
        test_tenant,
        "p2p_diaspora",
        "p2p",
        allowed_channels=["web", "mobile"],
    )

    # Narrow the base after the derived service was created.
    base.allowed_channels = ["web"]
    await db_session.commit()

    with pytest.raises(ServiceNotAllowedOnChannel):
        await resolve_service_code(
            db_session,
            tenant_id=test_tenant.id,
            base_code="p2p",
            requested_code="p2p_diaspora",
            channel="mobile",
        )

    resolved = await resolve_service_code(
        db_session,
        tenant_id=test_tenant.id,
        base_code="p2p",
        requested_code="p2p_diaspora",
        channel="web",
    )
    assert resolved == "p2p_diaspora"
