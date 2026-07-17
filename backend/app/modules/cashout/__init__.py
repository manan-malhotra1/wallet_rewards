"""Subscriber cash-out module — the mirror of agent cash-in.

A subscriber (consumer) names an agent by an identifier and sends money to that
agent: the subscriber is debited (principal + fee), the agent is credited the
principal and earns a platform-funded commission; fee + tax collect into the
system wallets. Reuses the Pricing v2 charge engine used by cash-in.
"""

from app.modules.cashout.router import router
from app.modules.cashout.service import cash_out

__all__ = ["cash_out", "router"]
