"""Audit module FastAPI router.

Endpoints:
  - GET /api/v1/audit — read the immutable audit_log, tenant-scoped

Previously served at `/api/v1/reconciliation/audit`; it moved here when the
provider redemption path (and with it the reconciliation module) was removed.
The log itself is untouched — every module still writes to it via
`audit.service`.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import get_current_admin
from app.modules.audit.query import query_audit_log
from app.modules.audit.schemas import AuditEntry
from app.shared.exceptions import InsufficientRole

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


def _require_finance_or_admin(
    admin: AdminPrincipal = Depends(get_current_admin),
) -> AdminPrincipal:
    """Read-side role gate — accept finance-reviewer OR platform-admin.

    Reading the audit log is a review activity, so finance-reviewer is
    enough; there is no write side on this router to gate more strictly.

    Raises:
        InsufficientRole: the caller holds neither role.
    """
    if not (admin.has_role("platform-admin") or admin.has_role("finance-reviewer")):
        raise InsufficientRole("finance-reviewer")
    return admin


@router.get("", response_model=list[AuditEntry])
async def get_audit(
    tenant_id: UUID,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[AuditEntry]:
    """Read the audit_log, tenant-scoped, newest first, windowed by
    limit/offset (B7.3 — the log grows for 7 years)."""
    _ = admin
    return await query_audit_log(
        session,
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
