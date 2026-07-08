"""Catalog module — user-facing rewards view (PRD Module 16).

Phase D delivers minimal endpoints: summary (available + lifetime earned +
lifetime redeemed) and redemption history. Badges, tiers, challenges, and
nudges are deferred to a later phase.
"""

from app.modules.catalog.router import router

__all__ = ["router"]
