"""RedemptionProvider and Redemption models — PRD §6.10.

Implements PRD Module 11. Phase D adds a FK from `redemption_providers` to
the provider's `provider_redemption_wallet` account (the CREDIT destination
on every redemption). This isn't in the PRD's literal schema but is the
natural relationship — the platform needs to know which wallet receives
points for each provider.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# Redemption status constants — keep in sync with the CHECK constraint.
REDEMPTION_STATUS_PENDING = "PENDING"
REDEMPTION_STATUS_PROCESSING = "PROCESSING"
REDEMPTION_STATUS_COMPLETED = "COMPLETED"
REDEMPTION_STATUS_FAILED = "FAILED"
REDEMPTION_STATUS_REVERSED = "REVERSED"
REDEMPTION_STATUS_MANUAL_REVIEW = "MANUAL_REVIEW"

REDEMPTION_TERMINAL_STATUSES = (
    REDEMPTION_STATUS_COMPLETED,
    REDEMPTION_STATUS_FAILED,
    REDEMPTION_STATUS_REVERSED,
)


class RedemptionProvider(Base):
    """An external partner that converts platform points into cash value.

    Each provider has one `provider_redemption_wallet` account (in PTS) that
    receives the CREDIT leg on every redemption. The link is explicit via
    `redemption_wallet_account_id` so the redemption code never has to guess
    which wallet to credit.
    """

    __tablename__ = "redemption_providers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_redemption_providers_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # FK to the system-owned provider_redemption_wallet account.
    redemption_wallet_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    status_check_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="3"
    )
    retry_interval_secs: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="300"
    )
    escalate_after_mins: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="60"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active"
    )
    # HMAC-SHA256 shared secret for verifying provider callback signatures
    # (Phase F.5, Pay-PRD-0495). NULL = provider has no automated callback;
    # all transitions must come through the admin `/confirm` + `/fail`
    # operator overrides.
    shared_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class Redemption(Base):
    """One user's redemption lifecycle (Pay-PRD-0660 to 0730).

    Status transitions enforced in code:
        PENDING -> PROCESSING -> COMPLETED
        PENDING -> FAILED
        PENDING -> REVERSED   (terminal — only when confirmed before fail)
        PENDING -> MANUAL_REVIEW (escalation)

    `transaction_id` links to the two-legged ledger transaction created at
    initiation. Status flips on that transaction's entries mirror the
    redemption status (PENDING -> COMPLETED on confirm; PENDING -> REVERSED
    on fail).
    """

    __tablename__ = "redemptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'PENDING', 'PROCESSING', 'COMPLETED', "
            "'FAILED', 'REVERSED', 'MANUAL_REVIEW'"
            ")",
            name="ck_redemptions_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("redemption_providers.id"), nullable=False
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    points_amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="PENDING"
    )
    # Idempotency key from initiate — unique per (tenant, key).
    # This duplicates `transactions.idempotency_key` for direct redemption
    # lookups but enables faster filtering.
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    provider: Mapped[RedemptionProvider] = relationship()
