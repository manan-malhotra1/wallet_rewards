"""Transaction and LedgerEntry models — PRD §6.6.

The ledger is the source of truth for every account balance. It is
APPEND-ONLY: entries are never UPDATEd or DELETEd. Reversals are new entries
with opposite direction. Balance is derived as `SUM(amount * sign)` per
account.

PRD references:
  - Pay-PRD-0170 to 0240 (Ledger module)
  - NFR-0100 (ledger sum-to-zero invariant)
  - NFR-0130 (no external calls inside DB transactions)

The non-negotiable invariants in `.claude/rules/ledger-invariants.md` govern
every write to these tables.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.models.base import Base, created_at_col, updated_at_col, uuid_pk

# Transaction status constants.
TXN_STATUS_PENDING = "PENDING"
TXN_STATUS_COMPLETED = "COMPLETED"
TXN_STATUS_FAILED = "FAILED"
TXN_STATUS_REVERSED = "REVERSED"

# LedgerEntry direction constants.
ENTRY_DEBIT = "DEBIT"
ENTRY_CREDIT = "CREDIT"

# LedgerEntry status constants.
ENTRY_STATUS_PENDING = "PENDING"
ENTRY_STATUS_COMPLETED = "COMPLETED"
ENTRY_STATUS_REVERSED = "REVERSED"


class Transaction(Base):
    """A movement of value between accounts.

    Every transaction owns ≥ 2 ledger entries (one DEBIT, one CREDIT) such
    that they balance to zero. The `idempotency_key` is unique per tenant
    (Pay-PRD-0200) — duplicate requests return the original transaction.

    Status transitions are enforced in code:
        PENDING -> COMPLETED | FAILED | REVERSED
    Terminal states (COMPLETED/FAILED/REVERSED) cannot transition further.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_transactions_idempotency_per_tenant",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'FAILED', 'REVERSED')",
            name="ck_transactions_status",
        ),
        Index("ix_transactions_status", "status", "tenant_id"),
        Index(
            "ix_transactions_user_created",
            "initiated_by",
            "tenant_id",
            "created_at",
        ),
        # Serves the segment metric registry's wallet-attributed transaction
        # aggregates (app.modules.segments.metrics): tenant + COMPLETED status +
        # a rolling created_at window, joined in from ledger_entries by
        # transaction_id. EXPLAIN on a 300k-row synthetic transactions table
        # showed this turns a parallel seq scan into a Bitmap Index Scan,
        # cutting the wallet-attributed txn_count/txn_sum query from ~358ms to
        # ~196ms (migration 0054).
        Index("ix_transactions_tenant_status_created", "tenant_id", "status", "created_at"),
        # Customer-facing reference is unique WITHIN a tenant — each tenant runs
        # its own `txn_ref_seq_<hex>` sequence, so two tenants can legitimately
        # share the same string. Partial (WHERE reference IS NOT NULL) so the
        # nullable backfill window doesn't collide many NULLs.
        Index(
            "uq_transactions_reference_per_tenant",
            "tenant_id",
            "reference",
            unique=True,
            postgresql_where=text("reference IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # Human-facing reference `S_<YYYYMMDDHHMMSS><NNNNNN>` — the timestamp part is
    # the creation instant (UTC) and NNNNNN a per-tenant running number drawn from
    # `txn_ref_seq_<tenant_hex>`. Nullable so the backfill migration can populate
    # it in a second pass; `post_transaction` always sets it on new rows.
    reference: Mapped[str | None] = mapped_column(String(40), nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # The BASE flow this transaction belongs to. Equals `transaction_type` for
    # transactions on a base service; for a derived service it names the base.
    # Denormalised so clients can group by flow without knowing every derived
    # code, and so history stays correct if a derived service is later deleted
    # (spec §12.1).
    # Defaults to `transaction_type` via a context-sensitive default rather than
    # requiring every caller to repeat it: for a BASE service the two are always
    # equal, so only a derived service ever passes something different. This also
    # means any code or test that builds a Transaction directly (bypassing
    # post_transaction) stays correct instead of tripping the NOT NULL.
    base_transaction_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=lambda ctx: ctx.get_current_parameters()["transaction_type"],
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=TXN_STATUS_PENDING
    )
    # NULL when the transaction is system-initiated (e.g. reward issuance).
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # NUMERIC(20, 6) for money + points without precision loss.
    amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    fee_amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False, server_default="0")
    # Display-only siblings to fee_amount (Pricing v2 Epic 20). The economics
    # already live in the balanced ledger legs; these surface the commission
    # paid to the acting agent and the total tax collected without re-deriving
    # them from the entries. Default 0 for every pre-v2 transaction.
    commission_amount: Mapped[float] = mapped_column(
        Numeric(20, 6), nullable=False, server_default="0"
    )
    tax_amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="transaction")


class LedgerEntry(Base):
    """A single DEBIT or CREDIT against one account.

    IMMUTABLE. No `updated_at` column — entries are never modified after
    insert. A reversal is a NEW entry with opposite direction. This is the
    structural guarantee for the append-only ledger invariant.

    Balance for account A = SUM(amount where entry_type='CREDIT') -
                            SUM(amount where entry_type='DEBIT')
    filtered by status='COMPLETED'.
    """

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('DEBIT', 'CREDIT')",
            name="ck_ledger_entries_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'REVERSED')",
            name="ck_ledger_entries_status",
        ),
        CheckConstraint(
            "amount > 0",
            name="ck_ledger_entries_amount_positive",
        ),
        Index(
            "ix_ledger_entries_account",
            "account_id",
            "status",
            "created_at",
        ),
        Index("ix_ledger_entries_transaction", "transaction_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=ENTRY_STATUS_PENDING
    )
    created_at: Mapped[datetime] = created_at_col()
    # NOTE: no updated_at — entries are immutable. See PRD Pay-PRD-0170.

    transaction: Mapped[Transaction] = relationship(back_populates="entries")
