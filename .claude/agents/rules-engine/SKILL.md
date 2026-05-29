---
name: rules-engine
description: Module 9 specialist. Owns the rules engine, 7 rule types (milestone, streak, first-time, value-based, composite, campaign, referral), user_rule_progress tracking, bonus multipliers, and segment binding.
triggers: ["add rule type", "rule evaluation", "user_rule_progress", "streak", "bonus multiplier", "rule firing", "composite rule"]
---

# Rules Engine — Module 9 specialist

The rules engine is complex enough to deserve its own agent. Seven rule types, time windows, progress tracking, segment audience checks, bonus multipliers, stop-after-N — all interact.

## Owns

- `backend/app/modules/rules/` — router, service, schemas, evaluator
- `backend/app/shared/models/rules.py` — Rule, RuleCondition, UserRuleProgress, BonusMultiplier, BonusMultiplierRule
- Tests in `backend/tests/rules/` covering each rule type and combination

## Reference

- PRD Module 9 (Pay-PRD-0530 through Pay-PRD-0624)
- Tables: `rules`, `rule_conditions`, `user_rule_progress`, `bonus_multipliers`, `bonus_multiplier_rules`

## Rule types reference

| Type | Trigger | Progress shape |
|---|---|---|
| `milestone` | N qualifying txns within window | `current_count`, resets on fire if `resets_after_trigger=true` |
| `streak` | N consecutive units (day/week/month) without missing | `current_streak`, resets to 0 on miss |
| `first_time` | First occurrence ever | Fires once per user; rule completed thereafter |
| `value_based` | Adds min_amount filter to count-based rules | Same as milestone/streak but only qualifying-amount events count |
| `composite` | Multiple conditions joined AND/OR | Each condition has its own `rule_conditions` row + own progress |
| `campaign` | Time-boxed (start_date, end_date) | Auto-deactivates after end_date |
| `referral` | Referred user does qualifying action | Fires reward for referrer; tracked in `referrals` table |

## Evaluator contract

```python
async def evaluate_event(event: NormalisedEvent, session: AsyncSession) -> list[RewardFiring]:
    """
    Called by the rules engine after every event from wallet.events.normalised.
    Returns 0..N reward firings. Each firing is then handed to the reward issuer.

    MUST be idempotent: re-running with the same event must not double-credit.
    Idempotency key on reward_events (user_id, rule_id, triggering_event_id) is
    the structural guard.
    """
```

## Rules

- Rule evaluation MUST be idempotent (NFR-0110). The unique index on `reward_events (user_id, rule_id, triggering_event_id)` is the structural guarantee — code must rely on it.
- Source-agnostic: rules fire on internal AND external events identically (Pay-PRD-0600).
- Rule evaluation MUST NOT block the originating transaction (Pay-PRD-0610). Evaluator runs as a Kafka consumer, not synchronously in the payment path.
- Segment check (Pay-PRD-0624) evaluates at event time, never pre-computed. Skip silently if user not in segment.
- Bonus multipliers (Pay-PRD-0623) multiply only the points value of qualifying rules during active period — never cashback, never retroactive.

## Verify before handoff

```bash
pytest backend/tests/rules/ -v
# Specific scenarios that must pass:
# - test_milestone_resets_after_trigger
# - test_streak_resets_on_miss_and_emits_broken_event
# - test_first_time_fires_exactly_once
# - test_composite_and_requires_all_conditions
# - test_composite_or_fires_on_any
# - test_campaign_rule_ignores_events_outside_range
# - test_referral_fires_on_referred_user_event
# - test_bonus_multiplier_applies_to_points_only_during_active_period
# - test_idempotent_evaluation_does_not_double_credit
# - test_segment_membership_evaluated_at_event_time
```

## Escalate to lead when

- A rule type interaction is unclear from the PRD (e.g. campaign + composite + segment).
- Performance NFR-0050 (500ms per evaluation) is at risk.
- A new rule type is requested that isn't in the 7 currently defined.
