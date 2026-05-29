"""Reconciliation module — sweep PENDING transactions, manual resolve, audit.

Implements PRD Module 12 (Pay-PRD-0750 to 0800). Phase E.1 delivers:
  - Sweep endpoint that finds stale PENDING redemptions, bumps retry_count,
    and escalates to MANUAL_REVIEW after `provider.max_retries`.
  - Manual resolve endpoint for operators to terminate MANUAL_REVIEW items.
  - Audit log writes on every action.

Deferred:
  - Real provider status_check_url call (Phase F — requires HMAC callbacks).
  - Celery-beat scheduling (manual HTTP trigger only in E.1).
"""
from app.modules.reconciliation.router import router

__all__ = ["router"]
