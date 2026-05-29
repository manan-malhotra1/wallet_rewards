"""Shared FastAPI dependencies.

Currently re-exports `get_async_session`. Add Keycloak-backed
`get_current_user`, `get_current_admin`, `get_current_tenant`
here when wiring up auth (Module 1).
"""
from app.database import get_async_session

__all__ = ["get_async_session"]
