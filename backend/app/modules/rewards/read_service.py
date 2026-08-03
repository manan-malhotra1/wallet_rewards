"""Mobile-facing rewards read model — `GET /me/rewards` + `POST /me/rewards/seen`.

Projects the rewards a signed-in user can see: the tenant's active rule catalog
with the caller's per-rule progress, plus the caller's most-recent reward
firings. Read-only except `mark_rewards_seen`, which flips the `seen_at` flag on
the caller's OWN reward_events (user-scoped, idempotent).

Rewards are a rewards-engine feature: a `wallet`-mode tenant returns
`enabled=False` with empty catalog/recent (see `app.shared.tenant_mode`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.segments.service import user_is_in_segment
from app.shared.models import (
    PROGRESS_STATUS_COMPLETED,
    REWARD_TYPE_POINTS,
    RULE_TYPE_MILESTONE,
    RULE_TYPE_STREAK,
    LedgerEntry,
    ReferralCode,
    RewardEvent,
    Rule,
    UserRuleProgress,
)
from app.shared.models.tenants import BUSINESS_TYPE_WALLET, Tenant

# Number of most-recent reward firings surfaced in the `recent` feed.
_RECENT_LIMIT = 20

# Human labels for the transaction types a rule can be tied to. Anything not
# mapped falls back to the raw type (or "activity" when a rule has no type).
_TXN_LABELS = {
    "p2p": "P2P transfers",
    "cash_in": "cash-ins",
    "cashout": "cash-outs",
}


def _txn_label(transaction_type: str | None) -> str:
    """Human-readable label for a rule's transaction_type (progress bar caption)."""
    return _TXN_LABELS.get(transaction_type or "", transaction_type or "activity")


def _reward_currency(reward_type: str, base_currency: str) -> str:
    """Derive a display currency: points are always 'PTS', cashback the tenant base.

    Neither `rules` nor `reward_events` stores a reward currency, so points map
    to the platform points unit and cashback to the tenant's base currency — the
    currency a cashback credit is actually paid in for a base-currency wallet.
    """
    return "PTS" if reward_type == REWARD_TYPE_POINTS else base_currency


async def _own_referral_code(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> str | None:
    """The caller's own shareable referral code, or None if they lack one.

    Read-only: older users created before referral codes existed have no row,
    and this path deliberately does NOT mint one (create happens only at signup).
    Sharing a code is independent of the rewards catalog, so this is surfaced
    even for a `wallet`-mode (rewards-disabled) tenant.
    """
    return (
        await session.execute(
            select(ReferralCode.code).where(
                ReferralCode.tenant_id == tenant_id,
                ReferralCode.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


def _progress_fired(progress: UserRuleProgress | None) -> bool:
    """True when a rule has fired at least once for the user (binary rule types)."""
    if progress is None:
        return False
    return progress.trigger_count > 0 or progress.status == PROGRESS_STATUS_COMPLETED


def _project(rule: Rule, progress: UserRuleProgress | None) -> dict[str, Any]:
    """Project one rule + the user's progress into `{current, target, label, status}`.

    The current/target pair depends on the rule_type:
      - milestone: current = matched-event count, target = the count_threshold
      - streak:    current = current streak, target = streak_units
      - everything else (first_time / value_based / campaign / composite /
        referral): binary — current = 1 once fired, target = 1

    status is "earned" once the progress row is completed, "in_progress" once
    current > 0, else "locked".

    Returns:
        A dict with the four projection keys — one catalog item's progress block
        merged with its status.
    """
    if rule.rule_type == RULE_TYPE_MILESTONE:
        current = progress.current_count if progress else 0
        target = rule.count_threshold or 0
    elif rule.rule_type == RULE_TYPE_STREAK:
        current = progress.current_streak if progress else 0
        target = rule.streak_units or 0
    else:
        # Binary rule types fire once; progress is all-or-nothing.
        current = 1 if _progress_fired(progress) else 0
        target = 1

    completed = progress is not None and progress.status == PROGRESS_STATUS_COMPLETED
    if completed:
        status = "earned"
    elif current > 0:
        status = "in_progress"
    else:
        status = "locked"

    return {
        "current": current,
        "target": target,
        "label": _txn_label(rule.transaction_type),
        "status": status,
    }


async def _eligible_rules(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> list[Rule]:
    """Active rules for the tenant, minus segment-bound rules the user isn't in.

    A rule with no `segment_id` is open to everyone; a segment-bound rule is
    included only when the caller is a member of that segment (reusing the same
    membership check the evaluator uses).
    """
    rules = (
        await session.execute(
            select(Rule)
            .where(Rule.tenant_id == tenant_id, Rule.status == "active")
            .order_by(Rule.created_at.asc())
        )
    ).scalars().all()

    eligible: list[Rule] = []
    for rule in rules:
        if rule.segment_id is not None and not await user_is_in_segment(
            session, user_id=user_id, segment_id=rule.segment_id
        ):
            continue
        eligible.append(rule)
    return eligible


async def list_my_rewards(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> dict[str, Any]:
    """Build the `GET /me/rewards` payload for the signed-in user.

    Returns the tenant's active rule catalog (each with the caller's progress +
    status) and the caller's ~20 latest reward firings. A `wallet`-mode tenant
    has no rewards engine, so it returns `enabled=False` with empty lists.

    Args:
        session: Async DB session.
        tenant_id: The caller's tenant (from the session token).
        user_id: The caller (from the session token).

    Returns:
        A dict with `enabled`, `referral_code`, `catalog`, and `recent` keys —
        validated by `RewardsOut`. `referral_code` is included regardless of
        `enabled`, since sharing a code is independent of the rewards catalog.
    """
    # Resolved first + surfaced unconditionally: a wallet-mode tenant has no
    # rewards engine but its users still own a shareable referral code.
    referral_code = await _own_referral_code(session, tenant_id=tenant_id, user_id=user_id)

    row = (
        await session.execute(
            select(Tenant.business_type, Tenant.base_currency).where(Tenant.id == tenant_id)
        )
    ).one_or_none()
    if row is None or row.business_type == BUSINESS_TYPE_WALLET:
        return {
            "enabled": False,
            "referral_code": referral_code,
            "catalog": [],
            "recent": [],
        }
    base_currency = row.base_currency

    rules = await _eligible_rules(session, tenant_id=tenant_id, user_id=user_id)

    # One progress lookup for all eligible rules, indexed by rule_id.
    progress_by_rule: dict[UUID, UserRuleProgress] = {}
    if rules:
        rows = (
            await session.execute(
                select(UserRuleProgress).where(
                    UserRuleProgress.user_id == user_id,
                    UserRuleProgress.rule_id.in_([r.id for r in rules]),
                )
            )
        ).scalars().all()
        progress_by_rule = {p.rule_id: p for p in rows}

    catalog: list[dict[str, Any]] = []
    for rule in rules:
        projection = _project(rule, progress_by_rule.get(rule.id))
        catalog.append(
            {
                "rule_id": rule.id,
                "name": rule.name,
                "description": rule.description,
                "reward_type": rule.reward_type,
                "reward_value": rule.reward_value,
                "currency": _reward_currency(rule.reward_type, base_currency),
                "status": projection.pop("status"),
                "progress": projection,
            }
        )

    recent = await _recent_rewards(session, user_id=user_id, base_currency=base_currency)
    return {
        "enabled": True,
        "referral_code": referral_code,
        "catalog": catalog,
        "recent": recent,
    }


async def _recent_rewards(
    session: AsyncSession, *, user_id: UUID, base_currency: str
) -> list[dict[str, Any]]:
    """The caller's latest reward firings (newest first), with rule name + currency.

    Currency comes from the linked ledger entry when present (the true paid
    currency); otherwise it is derived from the reward_type. `seen` reflects
    whether `seen_at` has been set.
    """
    rows = (
        await session.execute(
            select(RewardEvent, Rule.name, LedgerEntry.currency)
            .join(Rule, RewardEvent.rule_id == Rule.id)
            .outerjoin(LedgerEntry, RewardEvent.ledger_entry_id == LedgerEntry.id)
            .where(RewardEvent.user_id == user_id)
            .order_by(RewardEvent.created_at.desc())
            .limit(_RECENT_LIMIT)
        )
    ).all()

    recent: list[dict[str, Any]] = []
    for event, rule_name, ledger_currency in rows:
        recent.append(
            {
                "reward_event_id": event.id,
                "rule_name": rule_name,
                "reward_type": event.reward_type,
                "value": event.reward_value,
                "currency": ledger_currency or _reward_currency(event.reward_type, base_currency),
                "earned_at": event.created_at,
                "seen": event.seen_at is not None,
            }
        )
    return recent


async def mark_rewards_seen(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, reward_event_ids: list[UUID]
) -> int:
    """Flip `seen_at` on the caller's own unseen reward_events; return the count updated.

    User-scoped and idempotent: only rows owned by `user_id` AND still unseen
    (`seen_at IS NULL`) are touched, so re-posting the same ids marks 0 the
    second time and one user can never mark another's rewards. `tenant_id` is
    accepted for symmetry with the endpoint signature; reward_events are already
    fully constrained by `user_id` (a user belongs to exactly one tenant).

    Returns:
        The number of rows whose `seen_at` was set by this call.
    """
    if not reward_event_ids:
        return 0

    result = await session.execute(
        update(RewardEvent)
        .where(
            RewardEvent.user_id == user_id,
            RewardEvent.id.in_(reward_event_ids),
            RewardEvent.seen_at.is_(None),
        )
        .values(seen_at=datetime.now(UTC))
    )
    await session.commit()
    # execute() on an UPDATE returns a CursorResult; rowcount is the number of
    # matched (still-unseen, own) rows this call flipped.
    return cast("CursorResult[Any]", result).rowcount or 0
