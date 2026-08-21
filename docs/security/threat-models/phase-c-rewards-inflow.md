# Threat Model — Phase C Rewards Inflow

> **Date:** 2026-05-28
> **Reviewer:** security agent (inline)
> **PRD reference:** Pay-PRD-0480 to 0650 (Modules 8–10)
> **Code reference:** `backend/app/modules/{events,rules,rewards}/`

> ### ⚠ Correction — 2026-08-21
>
> This phase recorded S-1 as *mitigated* on the strength of HMAC verification. That
> verification was never wired into the Kafka consumer, and the "Phase F enforces" note below
> did not come true — F.5 built the verifier and enforced it on the HTTP routes only.
> **S-1 is open.** Tracked as **Epic SEC** in
> [`docs/09-epics-and-stories.md`](../../09-epics-and-stories.md).

---

## 1. What this phase delivers

End-to-end pipeline: **external Kafka event → rules engine → reward credit on user's points account**.

Scope (Phase C minimum viable):
- Event ingestion via Kafka topic `wallet.events.external`
- Event normalisation (standard schema; field_mapping JSONB for future flexibility)
- Source registration (each external system must be registered before its events are accepted)
- Deduplication via `event_ingestion_log` (Pay-PRD-0500)
- Rules engine — `first_time` and `milestone` rule types only
- Reward issuance: DEBIT `system_points_issuance` → CREDIT user's `points_account`
- Test HTTP endpoint that bypasses Kafka for synchronous testing
- Kafka consumer script for the real flow

Deferred to later phases:
- Streak, value-based, composite, campaign, referral rule types
- Bonus multipliers
- Segment binding
- Cashback reward type (points only in Phase C)
- HMAC signature verification (documented as accepted residual)
- Tier upgrades and badges
- Engagement event emission to WebEngage (`wallet.engagement.outbound`)

## 2. Data flow

```
[External Kafka producer]
   |
   |  Topic: wallet.events.external
   |  Body: { event_id, source_key, tenant_id, user_id, transaction_type,
   |          amount, currency, timestamp, ... }
   v
[Kafka consumer script (scripts/run_consumer.py)]
   |
   v
[events.service.process_external_event(raw)]
   |  1. Look up source_key in external_event_sources (must be active)
   |  2. (Optional) HMAC verify if source has shared_secret
   |  3. Check event_ingestion_log for (source_key, event_id) — skip if seen
   |  4. Normalise via field_mapping JSONB -> NormalisedEvent
   |  5. Insert event_ingestion_log row (PROCESSING)
   v
[rules.evaluator.evaluate_for_event(normalised)]
   |  For each active rule in the tenant matching transaction_type:
   |    - first_time: fire iff trigger_count == 0
   |    - milestone:  increment progress; fire if count == threshold; reset
   v
[rewards.service.issue_reward(...)]
   |  Insert reward_events (UNIQUE on user_id+rule_id+triggering_event_id)
   |  Call ledger.post_transaction:
   |    DEBIT  system_points_issuance
   |    CREDIT user.points_account
   v
[event_ingestion_log row updated -> PROCESSED]
```

## 3. Trust boundaries

| Boundary | What crosses | Trust assumption (Phase C) |
|---|---|---|
| Kafka topic → consumer | Raw event JSON | Anyone with broker access can publish — **still true, and no longer local-dev-only in effect**: the broker has no SASL and no ACLs (SEC.6), and the consumer does not verify signatures (SEC.1) |
| Consumer → events service | NormalisedEvent | source_key validated against `external_event_sources` |
| Events service → Rules evaluator | NormalisedEvent | Source already validated; tenant_id is from the event body (trusted) |
| Rules → Rewards → Ledger | RewardEvent + LedgerEntryRequest | Unique index on reward_events is the structural guarantee against double issue |

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|---|
| S-1 | Spoofing | Attacker writes to Kafka with fake `source_key` | High | Critical | Source must exist in `external_event_sources`. ~~HMAC verification (when secret set)~~ — never wired into the consumer | **⚠ OPEN** — see SEC.1 / SEC.2. Source registration alone is the control, and a `source_key` is not a secret |
| S-2 | Spoofing | Attacker forges `tenant_id` to credit themselves in another tenant | Med | Critical | source_key is tenant-scoped — verified that source.tenant_id == event.tenant_id | mitigated |
| T-1 | Tampering | Reward value modified between rule eval and issuance | Low | High | `reward_value` is read from `rules` table at issuance time, never trusted from event | mitigated |
| R-1 | Repudiation | Source denies sending an event | Low | Med | `event_ingestion_log` records every received event with timestamp + outcome | mitigated |
| I-1 | Info disclosure | Event payload leaks PII via logs | Med | Med | `mask_*` helpers; no full event body in app logs | mitigated by convention |
| I-2 | Info disclosure | Reward enumeration: caller queries reward_events to learn user activity | High (no auth) | Med | No reward query endpoint exposed in Phase C — only catalog endpoints in Phase D | accepted |
| D-1 | DoS | Spam Kafka with millions of events | Med | Med | Idempotency log dedupes; rules eval is per-event O(rules_per_tenant) | accepted |
| D-2 | DoS | Single event triggers many rules — fanout | Low | Low | Bounded by configured rule count per tenant | accepted |
| E-1 | Elevation | Caller creates a rule with reward_value = 10^9 | High (no auth on rule CRUD) | Critical | Rule CRUD endpoints flagged test-only; admin role check lands in Phase F | accepted |
| E-2 | Elevation | Rule with stop_after_n_triggers = NULL gives unlimited points | Med | High | By design — admin chooses. The check that admin endpoints require auth lands in Phase F. | accepted |

## 5. Project-specific test scenarios (handed to `automation-testing`)

1. **Source registration rejects duplicate `source_key`** — 409.
2. **Ingest rejects unregistered source** — event with unknown source_key is logged with status=REJECTED, no reward issued.
3. **Dedup: replayed event is no-op** — second event with same `(source_key, event_id)` returns no-op; no second reward, ingestion log shows DUPLICATE.
4. **First-time rule fires exactly once** — same user, same event_type, second occurrence → no second reward.
5. **Milestone rule counts qualifying events** — 4 transactions, threshold 5 → no fire. 5th transaction → fire.
6. **Milestone resets after fire** — after firing, the next event is treated as count=1 again.
7. **Inactive rule does not fire** — rule with `status='inactive'` is skipped.
8. **Tenant scoping** — rules and events scoped to tenant; event in tenant A doesn't fire rule in tenant B even with matching transaction_type.
9. **Reward double-issuance protection** — concurrent processing of same triggering_event_id: only one reward row written.
10. **Ledger sum-to-zero holds** after a series of rule firings.
11. **system_points_issuance balance trends negative** by exactly the sum of points issued.
12. **Reward value comes from rule, not event** — event sender cannot inject `reward_value`.

## 6. Residual risks accepted for Phase C

- **HMAC signature verification optional.** Sources without a shared_secret can publish unverified events. Documented as test-only acceptable for local dev. ~~Phase F enforces.~~ **⚠ This did not happen.** F.5 built the verifier and enforced it on the HTTP ingest routes; the Kafka consumer still passes neither the raw bytes nor the signature, and the secret is still optional at registration. Open as SEC.1 / SEC.2.
- **No auth on rule CRUD endpoints.** Anyone can create a million-point rule. Flagged test-only.
- **No auth on event ingestion HTTP endpoint.** Only used for test demos.
- **No segment binding.** Rules apply platform-wide within tenant. Phase D adds segments.
- **No tier upgrade emission.** Cumulative points → tier change deferred to Phase D.

## 7. Sign-off

- [x] STRIDE pass complete
- [x] Regression test list handed to automation-testing
- [x] PRD references cited
- Reviewed by: security agent (inline) on 2026-05-28
