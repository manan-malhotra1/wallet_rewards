"""Admin management of external-API keys (Epic 14 S2): create/list/revoke."""

from app.modules.api_keys.router import router

__all__ = ["router"]
