"""External partner-facing API (Epic 14). HMAC-authenticated, tenant-from-key."""

from app.modules.external.router import router

__all__ = ["router"]
