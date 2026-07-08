"""AirtimeRecharge model — Phase H follow-up to the topup correction.

A user-initiated airtime purchase: the wallet is DEBITed, the
`airtime_merchant_holding` account is CREDITed (PENDING) while the
third-party provider call is in flight. On provider success the
transaction moves PENDING -> COMPLETED; on failure a reversal pair
flips it to REVERSED; on timeout it stays PENDING and the existing
reconciliation sweep resolves it.

Mirrors the Redemption pattern (PRD §6.10) — same lifecycle, different
ledger accounts. Tests cover the full state machine.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# Airtime recharge status constants — keep in sync with CHECK constraint.
AIRTIME_STATUS_PENDING = "PENDING"
AIRTIME_STATUS_COMPLETED = "COMPLETED"
AIRTIME_STATUS_FAILED = "FAILED"
AIRTIME_STATUS_REVERSED = "REVERSED"

AIRTIME_TERMINAL_STATUSES = (
    AIRTIME_STATUS_COMPLETED,
    AIRTIME_STATUS_FAILED,
    AIRTIME_STATUS_REVERSED,
)


class AirtimeRecharge(Base):
    """One user's airtime recharge lifecycle.

    Status transitions enforced in service:
        PENDING -> COMPLETED   (provider confirms)
        PENDING -> FAILED      (provider rejects synchronously, no funds moved)
        PENDING -> REVERSED    (provider failure after funds were reserved)

    `transaction_id` links to the two-legged ledger transaction created at
    initiation. Status flips mirror the underlying transaction's status.
    """

    __tablename__ = "airtime_recharges"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'FAILED', 'REVERSED')",
            name="ck_airtime_recharges_status",
        ),
        # Idempotency at the recharge layer mirrors transactions —
        # duplicate (tenant, idempotency_key) returns the original row.
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_airtime_recharges_idempotency_per_tenant",
        ),
        Index("ix_airtime_recharges_tenant", "tenant_id"),
        Index("ix_airtime_recharges_user", "user_id"),
        Index("ix_airtime_recharges_status", "status", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # The number being recharged — typically the caller's own MSISDN but
    # nothing here enforces that (users may recharge a relative's phone).
    msisdn: Mapped[str] = mapped_column(String(20), nullable=False)
    # Carrier slug — "MTN", "Vodacom", "Cell C", "Telkom" in ZA. Free-form
    # for now; a provider registry similar to redemption_providers comes
    # in Phase 2.
    network: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=AIRTIME_STATUS_PENDING
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # Provider-returned reference (e.g. MTN voucher PIN, Vodacom recharge id).
    # Stored for ops + customer support lookups. Not PII.
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
