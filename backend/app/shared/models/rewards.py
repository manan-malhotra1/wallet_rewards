"""RewardEvent model — PRD §6.9.

The `(user_id, rule_id, triggering_event_id)` unique index is the structural
guarantee against double issuance (NFR-0110). Code MUST rely on this index —
never check-then-insert.

Badges, tiers, and challenges are scaffolded in PRD §6.9 but deferred to
Phase D (catalog).
"""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Numeric, String
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
    created_at: Mapped[datetime] = created_at_col()
