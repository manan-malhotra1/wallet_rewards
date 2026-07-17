"""Money-operation maker-checker module — N-eyes control for money moves (Epic 18).

Dual/N-control for treasury money movements (fund a user, withdraw from a user,
adjust a system wallet, create a bank mirror): a maker (platform-admin) proposes,
one or more distinct checkers (treasury-approver) approve, and only once the
tenant's required-approvals quorum is reached does the underlying treasury
function execute. Modelled on `config_requests` (Pricing v2 Epic 22).
"""

from app.modules.money_operations.router import router, serialize_money_operation
from app.modules.money_operations.service import (
    approve_money_operation,
    get_money_operation,
    list_money_operations,
    propose_money_operation,
    request_money_op_changes,
    resubmit_money_operation,
    revise_money_operation,
    withdraw_money_operation,
)

__all__ = [
    "approve_money_operation",
    "get_money_operation",
    "list_money_operations",
    "propose_money_operation",
    "request_money_op_changes",
    "resubmit_money_operation",
    "revise_money_operation",
    "router",
    "serialize_money_operation",
    "withdraw_money_operation",
]
