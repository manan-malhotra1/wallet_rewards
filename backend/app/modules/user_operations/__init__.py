"""User-operation maker-checker module — four-eyes for admin user create/edit.

Maker-checker control for administrator user-operations: a maker (platform-admin)
proposes a create-user or edit-user, one or more distinct checkers (user-approver)
approve, and only once the required-approvals quorum is reached does the identity
service execute the change. Modelled on `money_operations` (Epic 18).
"""

from app.modules.user_operations.router import router
from app.modules.user_operations.service import (
    approve_user_operation,
    get_user_operation,
    list_user_operations,
    propose_user_operation,
    request_user_op_changes,
    resubmit_user_operation,
    revise_user_operation,
    withdraw_user_operation,
)

__all__ = [
    "approve_user_operation",
    "get_user_operation",
    "list_user_operations",
    "propose_user_operation",
    "request_user_op_changes",
    "resubmit_user_operation",
    "revise_user_operation",
    "router",
    "withdraw_user_operation",
]
