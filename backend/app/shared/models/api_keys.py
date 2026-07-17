"""ApiKey model (Epic 14) — per-tenant credentials for the external API.

A partner authenticates to `POST /api/v1/external/users` with a public
`key_id` (sent in `X-Sasai-Api-Key`) and an HMAC signature over the request
computed with the key's secret. The secret is stored Fernet-encrypted in
`secret_encrypted` (Decision D3) so it stays recoverable for signature
verification but never sits in the database in the clear. The plaintext
secret is shown to the operator exactly once, at creation.

PRD references:
  - Pay-PRD-0010, 0050 (external creation reuses identity.create_user)
  - NFR-0170 (secrets never logged), NFR-0210 (HMAC replay window)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# Key lifecycle states — keep in sync with the CHECK constraint below + migration.
API_KEY_STATUS_ACTIVE = "active"
API_KEY_STATUS_REVOKED = "revoked"
API_KEY_STATUSES = (API_KEY_STATUS_ACTIVE, API_KEY_STATUS_REVOKED)


class ApiKey(Base):
    """A tenant-scoped API credential for the partner-facing external API."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    # Public, non-secret handle sent in X-Sasai-Api-Key. Globally unique so the
    # auth path can resolve key -> tenant without a separate tenant hint.
    key_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Fernet-encrypted secret (never plaintext) — recovered only to verify HMAC.
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional human label so operators can tell keys apart in the admin UI.
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # When set, this key acts as that merchant — its wallet is the funding
    # source for merchant_cashin. NULL for ordinary partner keys (fund/withdraw
    # ignore this column), so those keys are unaffected.
    merchant_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=API_KEY_STATUS_ACTIVE
    )
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked')", name="ck_api_keys_status"),
    )
