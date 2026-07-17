"""Rewards module — reward issuance (PRD Module 10, Pay-PRD-0620+).

Exposes `issue_points_reward` (points) and `issue_cashback_reward` (system-funded
money credit) — both internal, idempotent via the reward_events unique index.
"""

from app.modules.rewards.service import issue_cashback_reward, issue_points_reward

__all__ = ["issue_cashback_reward", "issue_points_reward"]
