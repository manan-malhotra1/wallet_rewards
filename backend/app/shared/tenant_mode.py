"""Single reader of `tenants.business_type` — the deployment-mode gate.

Every reward path consults this: wallet activity drives rewards only in
`both`; external Kafka events issue rewards only in `rewards`.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.exceptions import AppHTTPException
from app.shared.models.tenants import (
    BUSINESS_TYPE_BOTH,
    BUSINESS_TYPE_REWARDS,
    Tenant,
)


async def business_type_of(session: AsyncSession, tenant_id: UUID) -> str:
    """Return the tenant's business_type ('wallet' | 'rewards' | 'both').

    Args:
        session: Async DB session.
        tenant_id: The tenant to resolve.

    Returns:
        The stored business_type string.

    Raises:
        ValueError: No tenant exists with this id.
    """
    result = await session.execute(select(Tenant.business_type).where(Tenant.id == tenant_id))
    value = result.scalar_one_or_none()
    if value is None:
        raise ValueError(f"tenant {tenant_id} not found")
    return value


async def rewards_from_wallet_enabled(session: AsyncSession, tenant_id: UUID) -> bool:
    """True when internal wallet transactions should drive rewards (both mode).

    Non-raising by design: this runs on the `post_transaction` hot path, so an
    unresolved tenant must degrade to "no reward trigger" (False) rather than
    500 an otherwise-valid money movement. Queries business_type directly
    instead of delegating to `business_type_of` (which raises on a missing
    tenant — read endpoints rely on that).
    """
    result = await session.execute(select(Tenant.business_type).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none() == BUSINESS_TYPE_BOTH


async def external_events_allowed(session: AsyncSession, tenant_id: UUID) -> bool:
    """True when external Kafka events may issue rewards (rewards-only mode)."""
    return await business_type_of(session, tenant_id) == BUSINESS_TYPE_REWARDS


async def assert_points_scope_allowed(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    account_type: str | None = None,
    currency: str | None = None,
) -> None:
    """Reject points-denominated configuration for a tenant with no points programme.

    A wallet-only tenant has no PTS instrument and no points issuance account
    (B6.1), so a points-scoped pricing/limit/tax/commission row could never
    execute — it would be dead config of exactly the kind invariant #12 forbids.
    The UI hides the points options for such tenants, but the API is reachable
    directly, and a hidden dropdown is not enforcement.

    Args:
        account_type: The config row's account_type, if it has one.
        currency: The config row's currency, if it has one. Either dimension
            marks the row as points-scoped ('points_account' / 'PTS').

    Raises:
        AppHTTPException: 422 `points_not_available` when the tenant's mode has
            no points programme and the scope is points-denominated.
    """
    is_points_scoped = account_type == "points_account" or (currency or "").strip().upper() == "PTS"
    if not is_points_scoped:
        return
    mode = await business_type_of(session, tenant_id)
    if mode in (BUSINESS_TYPE_REWARDS, BUSINESS_TYPE_BOTH):
        return
    raise AppHTTPException(
        422,
        "points_not_available",
        "This tenant is wallet-only: it has no points programme, so "
        "points-denominated configuration cannot take effect here.",
    )
