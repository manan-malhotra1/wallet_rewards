"""Bulk commission disbursement and withdrawal — spec 2026-08-26 §8.

Two operator menus over one module: `disbursement` moves accrued commission
from a user's commission wallet into their main wallet; `withdrawal` claws it
back to an operator bank mirror. Both go through N-eyes maker-checker, reusing
the Epic 18 `approval_policies` quorum rather than reimplementing it.
"""

from app.modules.commission_batches.router import router

__all__ = ["router"]
