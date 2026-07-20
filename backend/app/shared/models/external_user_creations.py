"""ExternalUserCreation model — idempotency anchor for partner create-user.

`POST /api/v1/external/users` creates a user but posts NO ledger transaction,
so it has no `transactions.idempotency_key` to dedup on (unlike fund/withdraw).
This domain row records each successful external create's `Idempotency-Key` ->
`user_id` mapping, scoped per tenant, so a partner retry with the SAME key
replays the original user (200) instead of creating a second user or leaking a
409 (Pay-PRD-0200). A NEW key whose identifier is already taken is a genuine
409 — the store, not the identifier, is the idempotency key.

No PII is stored here — only the opaque idempotency key and the FK to the user.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, uuid_pk


class ExternalUserCreation(Base):
    """One successful partner create-user keyed by its `Idempotency-Key`.

    The `(tenant_id, idempotency_key)` unique constraint is the replay guard: a
    retry with the same key resolves to the original `user_id`. Two same-key
    requests racing collide on this constraint, so exactly one create wins and
    the other replays (see `external_create_user`).
    """

    __tablename__ = "external_user_creations"
    __table_args__ = (
        # Idempotency at the external-create layer — a duplicate
        # (tenant, idempotency_key) replays the original user (Pay-PRD-0200).
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_external_user_creations_idempotency_per_tenant",
        ),
        Index("ix_external_user_creations_tenant", "tenant_id"),
        Index("ix_external_user_creations_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_col()
