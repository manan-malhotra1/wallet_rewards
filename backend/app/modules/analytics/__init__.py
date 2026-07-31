"""Analytics module — read-only KPI aggregations for the admin dashboard.

Aggregates existing domain tables (transactions, users, ledger, redemptions)
into time-bucketed and grouped series. No writes, no ledger mutation; every
query is tenant-scoped per invariant 7.
"""
