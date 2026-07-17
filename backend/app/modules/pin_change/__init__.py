"""Change-PIN module — user self-service PIN change (charged, Pay-PRD-0420).

A user changes their own PIN. Change-PIN is a charged service subject to the
fail-closed gate (invariant #12), but has no principal — a zero-fee change moves
no money and posts no ledger legs, while a non-zero fee posts a fee-only
double-entry transaction. Idempotency + audit are anchored on the `pin_changes`
domain row, independent of the ledger.

Endpoint (see router.py):
  - POST /api/v1/pin/change   the authenticated user changes their own PIN.
"""

from app.modules.pin_change.router import router

__all__ = ["router"]
