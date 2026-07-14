"""Config governance module — maker-checker (Pricing v2 Epic 22).

Dual-control for pricing / limit / wallet-limit / commission / tax config
changes: a maker proposes, a different admin (config-approver) approves or
requests changes, and the maker revises + resubmits the same request until it
is approved (APPLIED) or withdrawn.
"""

from app.modules.config_requests.router import router
from app.modules.config_requests.service import (
    approve_config_request,
    get_config_request,
    list_config_requests,
    propose_config_change,
    request_config_changes,
    resubmit_config_request,
    revise_config_request,
    withdraw_config_request,
)

__all__ = [
    "approve_config_request",
    "get_config_request",
    "list_config_requests",
    "propose_config_change",
    "request_config_changes",
    "resubmit_config_request",
    "revise_config_request",
    "router",
    "withdraw_config_request",
]
