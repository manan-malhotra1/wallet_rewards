"""Single reader of `tenants.business_type` — the deployment-mode gate.

Every reward path consults this: wallet activity drives rewards only in
`both`; external Kafka events issue rewards only in `rewards`.
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    result = await session.execute(
        select(Tenant.business_type).where(Tenant.id == tenant_id)
    )
    return result.scalar_one_or_none() == BUSINESS_TYPE_BOTH


async def external_events_allowed(session: AsyncSession, tenant_id: UUID) -> bool:
    """True when external Kafka events may issue rewards (rewards-only mode)."""
    return await business_type_of(session, tenant_id) == BUSINESS_TYPE_REWARDS
