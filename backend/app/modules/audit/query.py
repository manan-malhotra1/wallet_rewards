"""Audit log read side — tenant-scoped query plus display-name enrichment.

The counterpart to `audit.service`, which only ever writes. Moved here from
the reconciliation module when the provider redemption path was removed: the
audit log records every module's state changes, so its reader never belonged
to one flow.

Enrichment is READ-SIDE ONLY — stored rows keep their stable ids and are
never mutated (NFR-0160: the table is append-only).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin_profiles.service import resolve_admin_names
from app.modules.audit.schemas import AuditEntry
from app.modules.identity.service import resolve_user_names
from app.shared.exceptions import TenantNotFound
from app.shared.models import ACTOR_ADMIN, ACTOR_SYSTEM, ACTOR_USER, AuditLog, Tenant


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject when the tenant_id is unknown — same pattern as elsewhere."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def query_audit_log(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditEntry]:
    """Read-side query over the audit_log table — tenant scoped.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope (required — never query without).
        entity_type: Optional filter (e.g. 'user').
        entity_id: Optional filter for a specific entity.
        offset: Rows to skip before the window starts (B7.3 pagination).
        limit: Hard cap on rows returned. Default 100.

    Returns:
        List of AuditEntry newest first.

    Raises:
        TenantNotFound: unknown tenant.
    """
    await _assert_tenant_exists(session, tenant_id)

    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    # id tie-break so a fixed window never duplicates/drops same-instant rows
    # (audit_log grows for 7 years — offset paging must be stable, B7.3).
    stmt = stmt.order_by(desc(AuditLog.created_at), desc(AuditLog.id)).offset(offset).limit(limit)

    rows = list((await session.execute(stmt)).scalars().all())
    return await _enrich_audit_entries(session, tenant_id=tenant_id, rows=rows)


def _parse_user_id(raw: str) -> UUID | None:
    """Best-effort parse of an id string into a UUID, else None.

    Audit `actor_id` / `entity_id` are free-form strings: only user references
    are UUIDs. A malformed value (e.g. a non-user entity_id) must never raise.
    """
    try:
        return UUID(raw)
    except (ValueError, AttributeError):
        return None


def _friendly_system_name(actor_id: str) -> str:
    """Friendly label for a system actor — 'API key' for apikey refs, else 'System'."""
    if actor_id.startswith("apikey:"):
        return "API key"
    return "System"


async def _enrich_audit_entries(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    rows: list[AuditLog],
) -> list[AuditEntry]:
    """Attach resolved `actor_name` / `entity_name` to a page of audit rows.

    Read-side only — the stored rows are never mutated. Resolution is batched:
    all admin subs resolve in ONE `resolve_admin_names` call and all user ids
    (actor-side and entity-side combined) in ONE `resolve_user_names` call, so
    there is no per-row query regardless of page size.

    Args:
        session: Async DB session (read-only).
        tenant_id: Tenant scope — user names never resolve across tenants.
        rows: The page of audit_log rows to enrich.

    Returns:
        AuditEntry models with `actor_name` / `entity_name` populated where
        resolvable, None otherwise (the UI falls back to the raw id).
    """
    # Collect the ids to resolve across the whole page, once per kind.
    admin_subs = {r.actor_id for r in rows if r.actor_type == ACTOR_ADMIN and r.actor_id}
    user_ids: set[UUID] = set()
    for r in rows:
        if r.actor_type == ACTOR_USER:
            parsed = _parse_user_id(r.actor_id)
            if parsed is not None:
                user_ids.add(parsed)
        if r.entity_type == "user":
            parsed = _parse_user_id(r.entity_id)
            if parsed is not None:
                user_ids.add(parsed)

    admin_names = await resolve_admin_names(session, admin_subs)
    user_names = await resolve_user_names(session, tenant_id=tenant_id, user_ids=user_ids)

    def _actor_name(r: AuditLog) -> str | None:
        if r.actor_type == ACTOR_ADMIN:
            return admin_names.get(r.actor_id)
        if r.actor_type == ACTOR_USER:
            parsed = _parse_user_id(r.actor_id)
            return user_names.get(parsed) if parsed is not None else None
        if r.actor_type == ACTOR_SYSTEM:
            return _friendly_system_name(r.actor_id)
        return None

    def _entity_name(r: AuditLog) -> str | None:
        if r.entity_type != "user":
            return None
        parsed = _parse_user_id(r.entity_id)
        return user_names.get(parsed) if parsed is not None else None

    entries: list[AuditEntry] = []
    for r in rows:
        entry = AuditEntry.model_validate(r)
        entry.actor_name = _actor_name(r)
        entry.entity_name = _entity_name(r)
        entries.append(entry)
    return entries
