"""AuditLog model — PRD §6.13.

Immutable audit trail for every administrator action and state transition
(NFR-0160, NFR-0250). The table has NO `updated_at` column — entries are
written once and never modified.

Every state-changing endpoint writes here via `app.modules.audit.service`;
`app.modules.audit.query` serves the admin read side.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, uuid_pk

# Actor type constants — keep in sync with the CHECK constraint.
ACTOR_USER = "user"
ACTOR_ADMIN = "admin"
ACTOR_SYSTEM = "system"


class AuditLog(Base):
    """One row per administratively interesting event.

    The before_state and after_state JSONB columns hold a snapshot of the
    affected entity. For state transitions, this lets reviewers see exactly
    what changed (e.g. user.status went active -> suspended, with the
    operator's reason in `note`).
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user', 'admin', 'system')",
            name="ck_audit_log_actor_type",
        ),
        Index("idx_audit_entity", "entity_type", "entity_id", "created_at"),
        Index("idx_audit_actor", "actor_id", "created_at"),
        # Serves the admin audit page's default view (tenant, newest-first,
        # LIMIT/OFFSET) — without it every unfiltered page load seq-scans and
        # top-N sorts a table that grows for 7 years (B7.3).
        Index("ix_audit_log_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # NULL when the action is platform-wide (no tenant scope).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    # Free-form identifier: user_id, admin Keycloak sub, or 'system' for jobs.
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    # Free-text note for human-readable context (e.g. reconciliation reason).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    # NO updated_at — audit entries are immutable (NFR-0160).
