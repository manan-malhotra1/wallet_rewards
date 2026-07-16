"""Commissions module — Pricing v2 Epic 19 (Story 19.3).

Platform-funded agent commissions: a schedule (`commission_configs`) and the
`calculate_commission` computation. The commission is credited to the acting
agent from the `commission` system pool by the charge assembler (Epic 20).
"""

from app.modules.commissions.router import router
from app.modules.commissions.service import (
    calculate_commission,
    create_commission_config,
    delete_commission_config_for_scope,
    list_commission_configs,
)

__all__ = [
    "calculate_commission",
    "create_commission_config",
    "delete_commission_config_for_scope",
    "list_commission_configs",
    "router",
]
