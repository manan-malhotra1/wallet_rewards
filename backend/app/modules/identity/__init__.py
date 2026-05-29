"""Identity module — user registration, identifier management, resolution.

Implements PRD Module 1 (Pay-PRD-0010 to 0100). Phase A delivers test-only
endpoints without auth; OTP/PIN flow lands in Phase 2.
"""
from app.modules.identity.router import router

__all__ = ["router"]
