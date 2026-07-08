"""Rewards module — reward issuance (PRD Module 10, Pay-PRD-0620+).

Currently exposes only `issue_points_reward` (internal). Cashback issuance
deferred to a later phase.
"""

from app.modules.rewards.service import issue_points_reward

__all__ = ["issue_points_reward"]
