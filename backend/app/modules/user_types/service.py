"""User-type catalog service — lookup, visibility and validation.

A tenant's visible types are the platform-wide system types (tenant_id IS NULL)
plus its own. Retired types are excluded from pickers but stay resolvable, so an
existing user or config row referencing one never falls through to the
`user_type IS NULL` default (spec §11).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import USER_TYPE_STATUS_ACTIVE, UserTypeDef


async def list_user_types(
    session: AsyncSession, tenant_id: UUID, *, include_retired: bool = False
) -> list[UserTypeDef]:
    """Return every user type visible to a tenant.

    Args:
        session: Async DB session (read-only).
        tenant_id: The acting tenant.
        include_retired: When True, retired types are included. Use this when
            rendering an existing config row so a retired type still shows its
            label rather than a raw code.

    Returns:
        System types plus the tenant's own, ordered by category then label.
    """
    stmt = select(UserTypeDef).where(
        or_(UserTypeDef.tenant_id.is_(None), UserTypeDef.tenant_id == tenant_id)
    )
    if not include_retired:
        stmt = stmt.where(UserTypeDef.status == USER_TYPE_STATUS_ACTIVE)
    stmt = stmt.order_by(UserTypeDef.category_code, UserTypeDef.label)
    return list((await session.execute(stmt)).scalars().all())


async def get_user_type(session: AsyncSession, tenant_id: UUID, code: str) -> UserTypeDef | None:
    """Resolve one type code for a tenant, retired included, or None.

    Retired types deliberately still resolve here. If they did not, an existing
    user carrying a retired type would fall through to the `user_type IS NULL`
    default config row and silently get default pricing and limits instead of
    being refused (spec §11).

    Args:
        session: Async DB session (read-only).
        tenant_id: The acting tenant — another tenant's custom type never resolves.
        code: The type code as stored on `users.user_type` / config rows.

    Returns:
        The matching row, preferring the tenant's own over a system type of the
        same code, or None when the code is not visible to this tenant.
    """
    stmt = (
        select(UserTypeDef)
        .where(
            UserTypeDef.code == code,
            or_(UserTypeDef.tenant_id.is_(None), UserTypeDef.tenant_id == tenant_id),
        )
        # A tenant row sorts before the system row (NULLs last), so a tenant
        # override wins if one somehow exists.
        .order_by(UserTypeDef.tenant_id.is_(None))
    )
    return (await session.execute(stmt)).scalars().first()
