"""Tenants module — admin-only listing of available tenants.

Powers the admin UI tenant switcher and the dashboard. The model itself
lives in `app.shared.models.tenants` (created in Phase A).
"""

from app.modules.tenants.router import router

__all__ = ["router"]
