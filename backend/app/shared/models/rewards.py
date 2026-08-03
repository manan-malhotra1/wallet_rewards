"""RewardEvent + RewardOutbox models — PRD §6.9.

The `(user_id, rule_id, triggering_event_id)` unique index is the structural
guarantee against double issuance (NFR-0110). Code MUST rely on this index —
never check-then-insert.

`RewardOutbox` is the durable trigger written atomically with a rewardable
wallet transaction and drained into the rules evaluator; stuck rows are the
reward reconciliation signal.

Badges, tiers, and challenges are scaffolded in PRD §6.9 but deferred to
Phase D (catalog).
"""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models.base import Base, created_at_col, uuid_pk


class RewardEvent(Base):
    """A single reward firing — one row per (user, rule, triggering event).

    The UNIQUE INDEX on (user_id, rule_id, triggering_event_id) is the
    idempotency mechanism for reward issuance (Pay-PRD-0620, NFR-0110).
    """

    __tablename__ = "reward_events"
    __table_args__ = (
        Index(
            "idx_reward_events_idempotency",
            "user_id",
            "rule_id",
            "triggering_event_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # Indexed standalone — supports rule-performance aggregation queries
    # (SUM/COUNT WHERE rule_id = ?) that can't use the composite idempotency
    # index above because rule_id isn't its leftmost column.
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.id"), nullable=False, index=True
    )
    # Free-text — could be a UUID (internal txn) or an external event_id.
    triggering_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reward_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reward_value: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    multiplier_applied: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, server_default="1.00"
    )
    # Link to the ledger entry on the user's points account that holds the credit.
    ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ledger_entries.id"), nullable=True
    )
    # When this event was picked up by a downstream consumer (e.g. notification
    # / delivery). NULL = not yet seen.
    seen_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


# reward_outbox.status
OUTBOX_PENDING = "pending"
OUTBOX_PROCESSED = "processed"
OUTBOX_FAILED = "failed"

# Wallet transaction types that drive rewards (loop-safe allowlist — excludes
# reward_issuance / cashback_reward / redemption).
REWARDABLE_TYPES = ("p2p", "cash_in", "cash_out", "airtime")


class RewardOutbox(Base):
    """Durable trigger written atomically with a rewardable wallet transaction.

    Drained (immediately post-commit and by a Celery recon sweep) into the
    rules evaluator. Stuck rows ARE the reward reconciliation signal. Carries
    `transaction_id` so a future reversal can look up and claw back.
    """

    __tablename__ = "reward_outbox"
    __table_args__ = (Index("idx_reward_outbox_tenant_status", "tenant_id", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=OUTBOX_PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    processed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
