"""Redemption module — convert user points into cash via external providers.

Implements PRD Module 11 (Pay-PRD-0660 to 0740). Phase D delivers the
synchronous initiate / confirm / fail / lookup endpoints. Reconciliation
sweep (Pay-PRD-0750) and the actual external provider HTTP call are
deferred — confirm/fail are simulated by admin/test endpoints in Phase D.
"""

from app.modules.redemption.router import router

__all__ = ["router"]
