# Threat Model — Phase D Redemption

> **Date:** 2026-05-29
> **Reviewer:** security agent (inline)
> **PRD reference:** Pay-PRD-0660 to 0740 (Module 11) + Pay-PRD-0970 to 1030 (Module 16 catalog)
> **Code reference:** `backend/app/modules/{redemption,catalog}/`

---

## 1. What this phase delivers

User converts earned points into cash value via a registered redemption provider.
The flow is the second half of the loop opened in Phase C (earn) — Phase D completes
the round trip (earn → redeem → realise value).

Scope (Phase D minimum viable):
- `redemption_providers` table + provider CRUD endpoints
- `redemptions` table tracking each user's redemption lifecycle
- `POST /api/v1/redemption/initiate` — atomic two-legged PENDING ledger write
  (Pay-PRD-0670)
- `POST /api/v1/redemption/{id}/confirm` — admin/test endpoint simulating
  provider success (Pay-PRD-0690)
- `POST /api/v1/redemption/{id}/fail` — admin/test endpoint simulating provider
  failure (Pay-PRD-0700) — restores user's points
- `GET /api/v1/redemption/{id}` — status lookup
- Catalog endpoints:
  - `GET /api/v1/catalog/{user_id}/summary` — available + lifetime earned +
    lifetime redeemed
  - `GET /api/v1/catalog/{user_id}/redemption-history`

Deferred to later phases:
- Real HTTP call to provider (replaced by test confirm/fail endpoints)
- Reconciliation sweep job (Pay-PRD-0750)
- MANUAL_REVIEW queue (Pay-PRD-0790)
- Points expiry, tier upgrades, badges, challenges (Module 16 §1010+)
- Auth (still Phase F)

## 2. Data flow

```
[Test HTTP client]                            [Admin/test caller]
   |                                              |
   |  POST /api/v1/redemption/initiate            |  POST /api/v1/redemption/{id}/confirm
   |  Idempotency-Key: <uuid>                     |        or /fail
   v                                              v
[Redemption service.initiate]                 [Redemption service.confirm | .fail]
   |                                              |
   |  1. Validate tenant + provider               |  1. Find redemption (tenant-scoped)
   |  2. Lock user.points_account                 |  2. Reject if not PENDING (terminal)
   |  3. Derive balance, check available          |  3. Flip ledger entries' status:
   |  4. Atomic 2-leg PENDING write:              |       - confirm: PENDING -> COMPLETED
   |     DEBIT  user.points  (PENDING)            |       - fail:    PENDING -> REVERSED
   |     CREDIT provider.wallet (PENDING)         |  4. Update transactions.status
   |  5. INSERT redemptions row (PENDING)         |  5. Update redemptions row
   v                                              v
[201 Created with redemption_id]              [200 with new status]

(In production the confirm/fail would be triggered by the provider's
async callback, NOT by an HTTP client. Phase D simulates for testing.)
```

## 3. Trust boundaries

| Boundary | What crosses | Trust assumption (Phase D) |
|---|---|---|
| HTTP → API | JSON body + Idempotency-Key | Pydantic validates; **no auth** — test-only endpoints |
| Service → Ledger | Balanced PENDING entries | Ledger re-validates double-entry balance + idempotency key |
| Service → Postgres lock | SELECT FOR UPDATE on user.points | Held until commit — serialises concurrent redemptions per user |
| Confirm/Fail → Redemption row | redemption_id from caller | Tenant scope re-checked; terminal-status check prevents double-completion |

## 4. STRIDE analysis

| ID | Category | Threat | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|---|
| S-1 | Spoofing | Caller submits another user's `user_id` to redeem from their points | High (no auth) | Critical | Accepted residual — endpoint test-only; Phase F resolves user from token | accepted |
| T-1 | Tampering | Replay same Idempotency-Key with different amount | Med | High | Idempotency check returns original transaction; second body ignored | mitigated |
| T-2 | Tampering | Caller tampers with redemption_id to confirm someone else's redemption | High (no auth) | High | Tenant scope enforced on confirm/fail lookups | mitigated (in-tenant); accepted for cross-actor without auth |
| R-1 | Repudiation | User denies initiating a redemption | Low | Med | `redemptions.created_at` immutable; `transactions.initiated_by` recorded | mitigated |
| I-1 | Info disclosure | Redemption history queryable for any user_id | High (no auth) | Med | Catalog endpoints flagged test-only; Phase F adds auth | accepted |
| I-2 | Info disclosure | Cross-tenant redemption lookup leaks existence | Med | Med | Tenant scoping → 404 (no leak) | mitigated |
| D-1 | DoS | Spam initiate with tiny amounts | Med | Low | No rate limit; row lock serialises per-user; budget caps in Phase G | accepted |
| D-2 | DoS | Long-running PENDING redemptions accumulate | Low | Low | Reconciliation sweep (Phase E) clears stale PENDING | accepted |
| E-1 | Elevation | Caller confirms own redemption (bypassing provider) | High (no auth) | Critical | Confirm endpoint is **test-only** in Phase D; production requires provider callback signature verification (Phase F) | accepted |

## 5. Project-specific test scenarios (handed to `automation-testing`)

1. **Provider registration auto-creates a redemption wallet** — one per provider.
2. **Initiate happy path** — Alice with 150 pts redeems 100 → PENDING redemption, PENDING ledger entries, available drops to 50.
3. **Initiate rejects insufficient points** — 200 redeem with only 150 → 409, no ledger write.
4. **Initiate idempotent on replay** — same key → same redemption_id, no second ledger entry.
5. **Concurrent double-spend blocked** — two simultaneous full-balance redemptions; only one wins.
6. **Confirm flips entries to COMPLETED** — balance permanently drops.
7. **Fail flips entries to REVERSED** — balance restored, available_balance back to pre-redemption.
8. **Confirm a non-PENDING redemption rejects** — 409 redemption_not_pending.
9. **Cross-tenant confirm rejects** — 404 redemption_not_found (no existence leak).
10. **Unknown provider rejects** — 404 provider_not_found.
11. **Catalog summary** — lifetime_earned + lifetime_redeemed match the ledger.
12. **Redemption history** — listed in reverse chronological order, tenant-scoped.
13. **`ledger_sum_to_zero` invariant** holds across initiate + confirm + fail cycles.

## 6. Residual risks accepted for Phase D

- No auth on initiate, confirm, fail, catalog endpoints.
- Confirm/fail endpoints simulate the provider — in production they would be
  provider-callback handlers with HMAC verification (Phase F).
- No reconciliation sweep — PENDING redemptions persist until manually
  confirmed/failed. Phase E adds the sweep.
- No notifications to the user (Pay-PRD-0640 deferred).
- No budget cap on the provider_redemption_wallet (would catch
  "provider runaway" scenarios — Phase G).

## 7. Sign-off

- [x] STRIDE pass complete
- [x] Regression test list handed to automation-testing
- [x] PRD references cited
- Reviewed by: security agent (inline) on 2026-05-29
