"""Agent cash-in module — Pricing v2 Epic 21.

An agent funds a customer's wallet from the agent's e-float and earns a
platform-funded commission; the fee + tax are collected into the system
wallets. First real consumer of the Pricing v2 charge engine.
"""

from app.modules.cashin.router import router
from app.modules.cashin.service import cash_in

__all__ = ["cash_in", "router"]
