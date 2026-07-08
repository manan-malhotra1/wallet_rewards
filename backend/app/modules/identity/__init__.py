"""Identity module — user registration, identifier management, resolution.

Implements PRD Module 1 (Pay-PRD-0010 to 0100). Phase F.4 gates direct
admin endpoints (`POST /users`, `GET /resolve/`) behind `platform-admin`
and exposes the public OTP/PIN flow for end-user authentication.
"""

from app.modules.identity.router import router

__all__ = ["router"]
