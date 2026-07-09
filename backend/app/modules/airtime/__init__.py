"""Airtime recharge module — the first merchant vertical (Epic 17).

A user buys airtime; the user wallet is DEBITed and the airtime merchant's
`airtime_merchant_holding` account is CREDITed (PENDING) while a third-party
provider provisions. The recharge finalises PENDING -> COMPLETED (success) or
PENDING -> REVERSED (failure -> refund); a slow provider leaves it PENDING for
the callback or reconciliation.

Endpoints (see router.py):
  - POST /api/v1/airtime/recharge   user-initiated purchase (auth-gated)
  - GET  /api/v1/airtime/{id}       tenant-scoped status lookup (poll)
"""

from app.modules.airtime.router import router

__all__ = ["router"]
