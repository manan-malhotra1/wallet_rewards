"""Ledger module — append-only double-entry bookkeeping.

Implements PRD Module 3 (Pay-PRD-0170 to 0240). No public HTTP router in
Phase A — the ledger is exposed via the Payments, Rewards, and Redemption
modules (Phases B/C/D). The service is consumed internally.

The invariants in `.claude/rules/ledger-invariants.md` are mandatory:
append-only, double-entry, idempotent, sum-to-zero, external calls after commit.
"""

from app.modules.ledger.service import (
    LedgerEntryRequest,
    PostTransactionRequest,
    build_reference,
    post_transaction,
    sum_completed_balance,
)

__all__ = [
    "LedgerEntryRequest",
    "PostTransactionRequest",
    "build_reference",
    "post_transaction",
    "sum_completed_balance",
]
