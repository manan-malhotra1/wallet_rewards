"""Resolve a user's user_type for type-aware pricing + limits (Epics 15/16).

The limits and pricing engines key their configs on the caller's user_type: an
exact-type config beats the `user_type IS NULL` default. This helper turns a
user_id into that type with one indexed lookup.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import USER_TYPE_CONSUMER, User


async def resolve_user_type(session: AsyncSession, tenant_id: UUID, user_id: UUID) -> str:
    """Return the user's user_type, or 'consumer' when the user is unknown.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope — the lookup is tenant-isolated.
        user_id: The acting user whose type drives config precedence.

    Returns:
        One of the five user types; falls back to `consumer` (the safe default,
        which also matches the NULL-default config row) if no user is found.
    """
    result = await session.execute(
        select(User.user_type).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none() or USER_TYPE_CONSUMER
