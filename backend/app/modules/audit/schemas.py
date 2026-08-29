"""Pydantic v2 schemas for the audit module's read side.

The writer (`audit.service`) builds ORM rows directly; only the query API
needs a wire shape. Lives here rather than in the module that used to own
the endpoint (`reconciliation`, removed with the provider redemption path)
because the audit log spans every module, not just one flow.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEntry(BaseModel):
    """Read-side representation of an audit_log row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID | None
    actor_id: str
    actor_type: str
    # Resolved human name for the actor (admin display name, user display name,
    # or a friendly "System" / "API key" label). None when unresolvable — the
    # UI falls back to `actor_id`. Read-side enrichment only; never stored.
    actor_name: str | None = None
    action: str
    entity_type: str
    entity_id: str
    # Resolved display name of the affected entity when `entity_type == 'user'`.
    # None for other entity types (the UI falls back to `entity_id`).
    entity_name: str | None = None
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    ip_address: str | None
    note: str | None
    created_at: datetime
