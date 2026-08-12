"""Package-internal helpers shared by `service.py` and `group_service.py`.

Not part of the public module surface (see `__init__.py`) — Task 7's segment
service imports these directly from the package internals rather than
duplicating them a third time.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.exceptions import AppHTTPException, TenantNotFound
from app.shared.models import SegmentGroup, Tenant

# Postgres SQLSTATE for a unique-constraint violation — the only IntegrityError
# cause a create() should translate into a 409; anything else (e.g. a NOT NULL
# violation) is a real bug and must not be swallowed.
UNIQUE_VIOLATION_SQLSTATE = "23505"


async def assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant is unknown."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def load_group_or_404(session: AsyncSession, group_id: UUID, tenant_id: UUID) -> SegmentGroup:
    """Return the tenant-scoped segment group, or 404 if it doesn't exist.

    The lookup filters on BOTH `group_id` and `tenant_id` — never 403 — a
    group's existence in another tenant is never leaked.

    Raises:
        AppHTTPException: 404 `segment_group_not_found`.
    """
    result = await session.execute(
        select(SegmentGroup).where(SegmentGroup.id == group_id, SegmentGroup.tenant_id == tenant_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise AppHTTPException(404, "segment_group_not_found", "Segment group not found.")
    return group
