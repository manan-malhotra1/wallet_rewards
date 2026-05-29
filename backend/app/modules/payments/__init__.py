"""Payments module — P2P, bill-pay, top-up orchestration.

Implements PRD Module 4 (Pay-PRD-0250 to 0320). Phase B delivers only P2P;
bill-pay and the public top-up endpoint are deferred to later phases. An
internal `top_up()` service function is provided so the seed can give users
opening balances via double-entry.
"""
from app.modules.payments.router import router

__all__ = ["router"]
