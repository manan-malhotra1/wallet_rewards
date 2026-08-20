"""RedemptionProvider, Redemption, and internal-redemption models — PRD §6.10.

Implements PRD Module 11 (external providers) and Module 11b (internal
redemption: `PointsConversionRate` + `InternalRedemption`, Pay-PRD-1200-1290,
design doc 07 §6). Phase D adds a FK from `redemption_providers` to the
provider's `provider_redemption_wallet` account (the CREDIT destination on
every external redemption).
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
    UniqueConstraint,
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
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    retry_interval_secs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="300")
    escalate_after_mins: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    # HMAC-SHA256 shared secret for verifying provider callback signatures
    # (Phase F.5, Pay-PRD-0495). Stored Fernet-encrypted at rest (Decision D3)
    # — recoverable via `decrypt_secret` because HMAC verification needs the
    # plaintext key at request time; a one-way hash wouldn't work. NULL =
    # provider has no automated callback; all transitions must come through
    # the admin `/confirm` + `/fail` operator overrides.
    shared_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="PENDING")
    # Idempotency key from initiate — unique per (tenant, key).
    # This duplicates `transactions.idempotency_key` for direct redemption
    # lookups but enables faster filtering.
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_checked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    provider: Mapped[RedemptionProvider] = relationship()


class PointsConversionRate(Base):
    """Per-(tenant, currency) points→fiat conversion rate (Pay-PRD-1210).

    Read as "`points_per_unit` PTS = `value_per_unit` `currency`" — e.g.
    100 PTS = 10.00 ZAR. Exactly one row per (tenant, currency); changes ride
    the config change-request maker-checker like pricing/limits. The internal
    redemption gate is FAIL-CLOSED on this table (Pay-PRD-1220): no ACTIVE row
    for the requested currency → 422 `conversion_rate_missing`, never a
    default rate.
    """

    __tablename__ = "points_conversion_rates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "currency", name="uq_points_conversion_rates_scope"),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_points_conversion_rates_status",
        ),
        CheckConstraint("points_per_unit > 0", name="ck_points_conversion_rates_points"),
        CheckConstraint("value_per_unit > 0", name="ck_points_conversion_rates_value"),
        CheckConstraint(
            "max_points_per_txn IS NULL OR max_points_per_txn > 0",
            name="ck_points_conversion_rates_txn_cap",
        ),
        CheckConstraint(
            "max_balance_pct_per_txn IS NULL OR "
            "(max_balance_pct_per_txn > 0 AND max_balance_pct_per_txn <= 100)",
            name="ck_points_conversion_rates_pct_cap",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    points_per_unit: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    value_per_unit: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    # Per-transaction anti-drain caps (Pay-PRD-1295). NULL = uncapped on that
    # axis: an absolute points ceiling, and/or a max percentage of the user's
    # CURRENT points balance a single redemption may burn.
    max_points_per_txn: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    max_balance_pct_per_txn: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class InternalRedemption(Base):
    """One completed internal redemption — the points↔fiat pair binding row.

    Cross-references the two balanced ledger transactions (Pay-PRD-1250/1260):
    the PTS burn (`points_transaction_id`) and the fiat payout
    (`payout_transaction_id`). The conversion rate is SNAPSHOTTED here so later
    rate changes never reinterpret history. Internal redemptions settle
    synchronously — there is no PENDING state and no reconciliation involvement.
    """

    __tablename__ = "internal_redemptions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_internal_redemptions_idempotency"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    points_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    payout_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    points_amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    fiat_amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    # Rate snapshot at redemption time (points_per_unit PTS = value_per_unit currency).
    points_per_unit: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    value_per_unit: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
