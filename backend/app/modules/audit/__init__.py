"""Audit log writer module (Phase F.5).

Cross-cutting helper used by every state-changing endpoint. Wraps the
common pattern of building an `AuditLog` row from a principal + a
before/after snapshot.
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
