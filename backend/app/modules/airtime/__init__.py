"""Airtime recharge module — placeholder.

Schema foundation (`airtime_merchant_holding` account type + migration
0015) lands in this commit; the service / router / provider abstraction
land in a follow-up. Once built, this module owns:

  - `POST /api/v1/airtime/recharge`         user-initiated airtime purchase
  - `POST /api/v1/airtime/{id}/callback`    HMAC-signed provider callback
  - `GET  /api/v1/airtime/{id}`             status lookup

Ledger semantics:
  DEBIT  user.financial_wallet
  CREDIT airtime_merchant_holding (per-tenant per-currency, lazy-created)

PENDING → COMPLETED on provider success; PENDING → REVERSED on failure
(refund leg flips the same accounts); PENDING stays for timeouts and is
resolved by the existing reconciliation sweep.
"""
