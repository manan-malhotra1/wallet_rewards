"""Accounts module — wallet, points, and system account management.

Implements PRD Module 2 (Pay-PRD-0110 to 0160). Balance is derived from
the ledger; this module owns the metadata (type, currency, owner) and the
balance read endpoint.
"""
from app.modules.accounts.router import router

__all__ = ["router"]
