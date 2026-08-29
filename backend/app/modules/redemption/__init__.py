"""Redemption module — convert user points into cash in the user's own wallet.

Implements PRD Module 11b (Pay-PRD-1200-1290): the points burn plus the fiat
payout, settled synchronously at the tenant's configured conversion rate. The
provider-fulfilled route that once sat alongside it (Pay-PRD-0660 to 0740) was
removed — points are already monetised into real money here, so a second,
externally-fulfilled path was redundant.
"""

from app.modules.redemption.router import router

__all__ = ["router"]
