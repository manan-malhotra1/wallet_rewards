"""Admin profile module — display-name cache for Keycloak admins (see model)."""

from app.modules.admin_profiles.service import record_admin, resolve_admin_names

__all__ = ["record_admin", "resolve_admin_names"]
