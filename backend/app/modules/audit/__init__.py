"""Audit log module (Phase F.5).

Two halves. The writer (`service`) is the cross-cutting helper every
state-changing endpoint calls, wrapping the common pattern of building an
`AuditLog` row from a principal plus a before/after snapshot. The reader
(`query` + `router`) serves the admin audit view; it moved here from the
reconciliation module when the provider redemption path was removed, since
the log spans every module rather than one flow.

Only the writer is re-exported here. `router` is imported from
`app.modules.audit.router` directly (as `app.main` does): the reader reaches
`identity.service`, and re-exporting it would drag that whole dependency
chain into every low-level module that just wants `record_audit`.
"""

from app.modules.audit.service import (
    record_audit,
    record_audit_for_admin,
    record_audit_for_system,
    record_audit_for_user,
)

__all__ = [
    "record_audit",
    "record_audit_for_admin",
    "record_audit_for_system",
    "record_audit_for_user",
]
