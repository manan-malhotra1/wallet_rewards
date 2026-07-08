"""Roles & Permissions module — PRD Module 7.

Per-tenant named roles with per-transaction-type permissions.
Step 1 of the Pay-PRD-0260 orchestration sequence consumes the
`has_permission` check before any payment moves forward.
"""

from app.modules.roles.router import router

__all__ = ["router"]
