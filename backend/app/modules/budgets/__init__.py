"""Reward budgets module — Phase G.1.

Caps how much can be issued per (tenant, scope, currency, window). The
`issue_points_reward` service calls `check_budget_available()` BEFORE
writing any ledger entries.
"""
from app.modules.budgets.router import router
from app.modules.budgets.service import (
    check_budget_available,
    create_budget,
    delete_budget,
    list_budgets_for_tenant,
)

__all__ = [
    "router",
    "check_budget_available",
    "create_budget",
    "delete_budget",
    "list_budgets_for_tenant",
]
