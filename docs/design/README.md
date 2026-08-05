# Design & Architecture — Sasai Wallet & Rewards Platform

> **Document type:** High-Level Design (HLD) + index to the per-module design docs.
> **Companion to:** the [Product PRD](../02-prd.md) (the *what* — requirements + acceptance criteria) and
> [Epics & Stories](../09-epics-and-stories.md) (delivery tracking). This folder is the ***how*** — it explains
> how each PRD requirement is actually built. When a design doc conflicts with the PRD, the PRD wins on
> *intent*; the design doc wins on *current implementation*.
> **Audience:** an engineer joining the project. Read this file first, then the module doc for your area.
> **Last reviewed:** 2026-08-05 (reflects `main`).

---

## 1. What this platform is

A multi-tenant **wallet + rule-based rewards engine** for Sasai Fintech's diaspora ecosystem. Two capabilities
that ship together or independently:

- **Wallet** — a stored-value account. Money is received, held, and spent inside the ecosystem (P2P, agent
  cash-in/cash-out, airtime, redemptions), recorded on an append-only double-entry ledger.
- **Rewards & engagement engine** — a configurable rule engine that watches transaction activity (internal
  wallet events *or* external partner events over Kafka) and issues points / cashback rewards.

The two are bound by a per-tenant **deployment mode** (`business_type`), which is *load-bearing* — it decides
which subsystems are live for a tenant (see §3).

---

## 2. Technology stack (locked by the Technical PRD)

| Layer | Tech | Version |
|---|---|---|
| Backend | Python · FastAPI · SQLAlchemy 2.0 (async) · Alembic · Pydantic v2 | 3.12 / 0.136.3 / 2.0.50 / 1.18.4 |
| Database | PostgreSQL | local instance |
| Bus | Apache Kafka · confluent-kafka | Docker |
| Queue | Celery · Redis | latest |
| Admin auth | Keycloak (JWT/JWKS, RS256) | Docker |
| User auth | Custom PIN/OTP + Redis sessions | — |
| Admin UI | Next.js 16 (App Router) · TypeScript · shadcn/ui · Tailwind v4 · next-auth v5 | Node 22 |
| Mobile | Expo (SDK 54) · React Native · expo-router · Tamagui · Skia · TanStack Query | Node 22 |

The backend is a **modular monolith**: one deployable, one module per domain folder under `backend/app/modules/`.
Module extraction into services is a Phase-2 decision (Assumption A-01).

---

## 3. Deployment modes (`tenants.business_type`) — the master switch

Resolved centrally in `backend/app/shared/tenant_mode.py`. Every rewards decision routes through it.

| Mode | Wallet money paths | Rewards from wallet activity | External Kafka events |
|---|---|---|---|
| `wallet` | ✅ live | ❌ none issued | ❌ rejected (`wrong_mode`) |
| `rewards` | ❌ (rewards-only) | — | ✅ **only** source of events |
| `both` | ✅ live | ✅ via internal transactional **outbox** | ❌ rejected (`wrong_mode`) |

- `rewards_from_wallet_enabled(tenant)` → true only in `both` (non-raising; degrades to false on the hot path).
- `external_events_allowed(tenant)` → true only in `rewards`.

This is why a `both`-mode tenant drives rewards from its own wallet transactions **without** an external Kafka
consumer, while a `rewards`-only tenant is driven **exclusively** by partner events. See
[06-events-ingestion-and-mode-awareness](06-events-ingestion-and-mode-awareness.md).

---

## 4. Repository map

| Path | What lives here |
|---|---|
| `backend/app/modules/{domain}/` | Per-domain service: `router.py` (no business logic) → `service.py` → `schemas.py` |
| `backend/app/shared/models/` | SQLAlchemy ORM, one file per domain |
| `backend/app/shared/exceptions/` | All custom exceptions (one file, ~100 classes, all subclass `AppHTTPException`) |
| `backend/app/auth/` | Keycloak JWT, Redis sessions, bcrypt hashing, HMAC callbacks, API-key + rate-limit |
| `backend/alembic/versions/` | Migrations (`YYYYMMDD_NNNN_description.py`) — the *only* place DDL is allowed |
| `admin-ui/app/(authenticated)/` | Next.js admin pages (App Router; server components + `_actions.ts` server actions) |
| `mobile/app/` | Expo screens (expo-router file-based) |
| `sasai-wallet-infra/` | Docker Compose (Postgres, Kafka, Keycloak, Redis) + `kafka/topics.sh` |
| `scripts/` | `seed.py`, `check_migrations.py`, `bootstrap_keycloak.py`, `run_consumer.py` |
| `docs/` | Vision, PRD, epics, this design folder, UX/UI, architecture, security threat models |
| `.claude/` | Agents, path-scoped rules, skills, memory |

Local setup end-to-end is the [`local-setup` skill](../../.claude/skills/local-setup/SKILL.md).

---

## 5. The money core — one choke point, one guard

**Every** movement of value (P2P, cash-in, cash-out, airtime, change-PIN fee, redemption, treasury
fund/withdraw/adjust, external partner fund/withdraw/merchant-cashin, reward issuance/cashback) funnels through a
**single function**: `ledger.service.post_transaction`. Nothing writes ledger entries any other way.

Non-negotiable invariants enforced there (full detail in
[02-ledger-accounts-and-money-movement](02-ledger-accounts-and-money-movement.md)):

1. **Append-only ledger.** No `UPDATE`/`DELETE` on `ledger_entries`. Reversals append opposite-direction legs.
   Balance = `SUM(ledger_entries)` (COMPLETED); reserved = PENDING debits.
2. **Idempotency first.** Unique `(tenant_id, idempotency_key)` on `transactions`; a duplicate key returns the
   original result with no new rows (Pay-PRD-0200).
3. **The `FOR UPDATE` balance guard** (the M-01 fix). Per touched account, net delta is computed; only
   `financial_wallet` and the `system_cash_inflow` **cash float** are guarded (all pool/collection/points
   accounts are skipped). Guarded rows are locked in canonical (id-sorted) order *before* any balance read and
   held through commit — never across an external call. It enforces: overdraft rejection on any net debit
   (`InsufficientFunds`, or `InsufficientFloat` for the float), the `max_balance` ceiling on user-wallet credits,
   and the **non-negative cash-float floor** (the float must be pre-funded from the bank before it can fund
   users). Reversals and earned payouts (agent commission credit) are **cap-exempt** (fail-open).
4. **Fail-closed pricing + limits.** Before any ledger write, `require_pricing_and_limits` requires BOTH a
   pricing config AND a limit config to resolve for the acting user's type — else `422` (Pay-PRD-0420). No silent
   zero-fee/limitless pass-through. See [03-money-controls](03-money-controls-pricing-limits-roles-step-up.md).
5. **External calls after commit only** (NFR-0130). Airtime/redemption reserve funds PENDING, dispatch to the
   provider after the DB transaction closes, and settle on callback/sweep.

The standard per-transaction order (assembled in each money service):
`assert_user_can_transact → require_permission → assert_service_allowed → require_pricing_and_limits →
check_limits + wallet send/receive caps → enforce_step_up → assemble_charges → post_transaction → external call`.

---

## 6. Governance — maker-checker everywhere money or config moves

Three parallel maker-checker subsystems share one shape (propose → PENDING → checker approve / request-changes →
maker revise/resubmit/withdraw → apply-on-approval in one transaction), surfaced to admins as a single
`/approvals` inbox. Detail in [04-maker-checker-and-approvals](04-maker-checker-and-approvals.md).

| Subsystem | Governs | Checker role |
|---|---|---|
| `config_requests` | pricing / limit / wallet-limit / tax / commission / step-up config | config-approver |
| `money_operations` | treasury fund / withdraw / adjust-float / bank-mirror (N-eyes) | treasury-approver |
| `user_operations` | admin create / edit user (four-eyes) | user-approver |

No self-approval; N-eyes needs N *distinct* approvers; apply uses a deterministic idempotency key so
re-approval/replay can't double-post; every action writes an immutable `audit_log` row.

---

## 7. Rewards, rules & referral

The rules engine evaluates 7 rule types (milestone, streak, first_time, value_based, campaign, composite,
referral) against a normalised event, tracks per-user progress, and issues rewards idempotently
(`reward_events` unique on `(user_id, rule_id, triggering_event_id)`). Points are auto-provisioned; cashback
credits the financial wallet cap-exempt. In `both` mode a completed rewardable wallet transaction writes a
`reward_outbox` row atomically with the ledger commit; a post-commit fast path plus a 60s Celery sweep drain it
(absolute fail-open — rewards never break the money path). Referral rewards fire only when a code was used, only
at PIN-set (verified signup), both-sided, admins excluded. Detail:
[05-rewards-rules-and-referral](05-rewards-rules-and-referral.md).

---

## 8. Cross-cutting

Tenancy (`tenant_id` on every domain table; isolation enforced at query level), the immutable `audit_log`
(7-year retention), PII masking in logs, HMAC proof-of-origin on external event sources + provider callbacks,
per-tenant admin branding, and the read-only per-currency analytics dashboard (money never summed across
currencies; revenue = operator fee only). Detail in
[11-cross-cutting-observability-compliance-security](11-cross-cutting-observability-compliance-security.md) and
the path-scoped rules in [`.claude/rules/`](../../.claude/rules/).

---

## 9. Design document index

| Doc | Covers | PRD modules |
|---|---|---|
| [01 — Identity, Auth & Users](01-identity-auth-and-users.md) | identity/resolution, PIN/OTP/session, self-registration, user types, admin user governance, access control | 1, 7 (partial) |
| [02 — Ledger, Accounts & Money Movement](02-ledger-accounts-and-money-movement.md) | account model, append-only ledger, `post_transaction` choke point + balance guard, P2P/cash-in/cash-out/airtime/change-PIN/treasury | 2, 3, 4 |
| [03 — Money Controls: Limits, Pricing, Roles, Step-up](03-money-controls-pricing-limits-roles-step-up.md) | limits (type-aware, wallet caps), slab pricing + commission + tax, fail-closed gate, RBAC, step-up PIN, reward budgets | 5, 6, 7 |
| [04 — Maker-Checker & Approvals](04-maker-checker-and-approvals.md) | config/money/user maker-checker, unified `/approvals`, N-eyes, dup-identifier guard | 1/6/14 governance |
| [05 — Rewards, Rules & Referral](05-rewards-rules-and-referral.md) | 7 rule types + evaluator, issuance + multipliers + budgets, segments, referral end-to-end | 9, 10, 15 |
| [06 — Events Ingestion & Mode Awareness](06-events-ingestion-and-mode-awareness.md) | event sources, HMAC, dedup, normalisation, Kafka, `business_type` gating, reward outbox pipeline, engagement-emission gap | 8, 17 |
| [07 — Redemption & Reconciliation](07-redemption-and-reconciliation.md) | redemption lifecycle + points lock, reconciliation sweep / manual review / audit query | 11, 12 |
| [08 — Tenancy, Config & Provisioning](08-tenancy-config-and-provisioning.md) | tenants, instruments, services + access policy, auto-provisioning, per-tenant branding, API keys, external partner API | 14 |
| [09 — Admin UI](09-admin-ui.md) | Next.js architecture, server actions, app shell, per-page design, branding engine, approvals UI | — |
| [10 — Mobile App](10-mobile-app.md) | Expo architecture, backend-URL resolution, API client, screens, step-up pattern, rewards/celebration | 16 |
| [11 — Cross-cutting: Observability, Compliance, Security](11-cross-cutting-observability-compliance-security.md) | logging/masking, audit, retention, tenant isolation, encryption, analytics, threat models | NFRs |
| [12 — Testing & Automation](12-testing-and-automation.md) | backend pytest (API/Kafka/ledger-invariant/idempotency) + coverage gate, frontend Vitest, `make check`/CI, ownership | NFRs |

See also the system-level [Technical Architecture](../05-technical-architecture.md) and
[Data Architecture](../06-data-architecture.md) (higher-level summaries), and the admin
[UX Philosophy](../03-ux-philosophy.md) / [UI Layouts](../04-ui-layouts.md).

---

## 10. Known gaps (as of 2026-08-05)

These are documented as requirements in the PRD but are **not yet built** — do not assume they exist:

- **Module 13 Notifications** — no notifications module; only an in-app mobile reward-celebration exists. No
  SMS/push/email dispatch.
- **Module 17 External Engagement Emission** — Kafka topics (`wallet.rewards.issued`,
  `wallet.engagement.outbound`) are reserved in config, but no producer / WebEngage connector is implemented.
- **Composite `transactions`-counting & referral `nth_transaction`** — logic is built and unit-tested but not
  yet wired to the live internal-transaction pipeline (the evaluator historically ran off external events; the
  `both`-mode outbox now feeds internal events, but the transaction-count sources are not fully wired).
- **Rewards catalog extras** (tiers, badges, challenges, points-expiry) — schema exists; user-facing surfaces
  are Planned.
- **Reversal claw-back of rewards** — `reward_outbox.transaction_id` is recorded for a future hook; not built.

See the [Epics & Stories](../09-epics-and-stories.md) *Delivery snapshot* and *Conflicts* sections for the full
Shipped / Partial / Planned picture.
