"""Audit log writer (Phase F.5).

One canonical place every state-changing endpoint calls to record an
`audit_log` entry. Centralising the write means we never forget the
actor_type / actor_id convention from `compliance-fintech.md`.

The writer ADDS the row to the session — it does NOT commit. Callers
commit alongside the domain-state change so the audit row lands or
disappears atomically with the action it records.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principals import AdminPrincipal, UserPrincipal
from app.shared.models import AuditLog
from app.shared.models.audit import ACTOR_ADMIN, ACTOR_SYSTEM, ACTOR_USER


def record_audit(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    actor_id: str,
    actor_type: str,
    action: str,
    entity_type: str,
    entity_id: str,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    ip_address: str | None = None,
    note: str | None = None,
) -> AuditLog:
    """Add one `audit_log` row to the session (caller commits).

    Args:
        session: Async DB session. The row is added; the caller commits.
        tenant_id: Scope. None only for platform-wide actions.
        actor_id: User UUID, Keycloak `sub`, "system", or a prefixed system
            identifier like "provider:<uuid>" / "source:<key>".
        actor_type: One of `user`, `admin`, or `system`.
        action: Convention `<entity>.<verb>` — e.g. `redemption.confirmed.by_provider`.
        entity_type: The table or domain object name (e.g. "redemption").
        entity_id: Stringified PK.
        before_state, after_state: JSONB snapshots — usually a dict of the
            fields that changed.
        ip_address: IPv4/IPv6 of the caller. Pulled from `request.client.host`.
        note: Free-text human-readable context.

    Returns:
        The unsaved `AuditLog` ORM object — useful if the caller wants to
        attach it as a related row.

    Side effects:
        Adds the row to `session`. Does NOT call `session.commit()`.
    """
    row = AuditLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        ip_address=ip_address,
        note=note,
    )
    session.add(row)
    return row


def record_audit_for_admin(
    session: AsyncSession,
    admin: AdminPrincipal,
    *,
    tenant_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: str,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    ip_address: str | None = None,
    note: str | None = None,
) -> AuditLog:
    """Shortcut — actor resolved from an authenticated AdminPrincipal."""
    return record_audit(
        session,
        tenant_id=tenant_id,
        actor_id=admin.id,
        actor_type=ACTOR_ADMIN,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        ip_address=ip_address,
        note=note,
    )


def record_audit_for_user(
    session: AsyncSession,
    user: UserPrincipal,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    ip_address: str | None = None,
    note: str | None = None,
) -> AuditLog:
    """Shortcut — actor resolved from an authenticated UserPrincipal.

    The principal always carries a tenant_id; we use that as the audit
    row's tenant_id so cross-tenant audit queries stay correct.
    """
    return record_audit(
        session,
        tenant_id=user.tenant_id,
        actor_id=str(user.id),
        actor_type=ACTOR_USER,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        ip_address=ip_address,
        note=note,
    )


def record_audit_for_system(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: str,
    actor_id: str = ACTOR_SYSTEM,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    note: str | None = None,
) -> AuditLog:
    """Shortcut for jobs + verified third-party callbacks.

    `actor_id` defaults to the bare string "system" for background jobs.
    For verified provider callbacks pass `actor_id="provider:<uuid>"`; for
    verified event-source ingestion pass `actor_id="source:<source_key>"`.
    """
    return record_audit(
        session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_type=ACTOR_SYSTEM,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        note=note,
    )
