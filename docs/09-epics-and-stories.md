# Epics & Stories — Sasai Wallet & Rewards Platform

> **What this document is.** The single canonical, de-duplicated Epic → Story backlog for the
> Sasai Wallet & Rewards platform. It consolidates every prior backlog, initiative plan,
> threat model, and architectural-memory source into one delivery-oriented record of *what* the
> platform delivers and *what state* each capability is in.
>
> **How it relates to the other docs.**
> - **PRD** ([`docs/02-prd.md`](02-prd.md)) = the *requirements* view: WHAT the platform must do, organised by
>   the 17 functional modules (`Pay-PRD-XXXX`). The PRD is the source of truth for behaviour.
> - **This doc** = the *delivery* view: the same capabilities re-cut as Epics and Stories with a
>   shipped/planned status, so anyone can see how much of the PRD is actually built.
> - **`docs/design/` and `docs/superpowers/specs/`** = the *HOW*: implementation designs. This doc never
>   describes mechanics — acceptance criteria here are observable behaviour and guarantees only.
>
> **Status legend.**
> - **Shipped** — on `main`, confirmed by code inventory + architectural memory.
> - **Partial** — some stories shipped, a named residual open.
> - **Planned** — designed/backlogged, not built.
>
> **Numbering.** Backlog epic numbers (1–28) and initiative labels (A/B/C, DASH, MOB, HARD) are
> preserved as-is. The one exception is the historical **Epic-18 collision** (two different features
> shared the number 18): the threat-model "External Partner Treasury" feature is relabelled
> **Epic 18S** here so the number is unambiguous. See *Conflicts, numbering & provenance*.

---

## Epic index

| Epic | Title | Status | Stories | Primary PRD module(s) |
|---|---|---|---|---|
| 1 | Foundation — Identity + Accounts + Ledger | Shipped | 6 | 1 Identity · 2 Account · 3 Ledger |
| 2 | P2P Transfer | Shipped | 3 | 4 Payment Orchestration |
| 3 | Kafka Rewards Inflow | Shipped | 5 | 8 Event Ingestion · 9 Rules · 10 Reward Issuance |
| 4 | Redemption + Catalog | Shipped | 7 | 11 Redemption · 16 Rewards Catalog |
| 5 | Reconciliation + Admin UI | Partial | 7 | 12 Reconciliation · 14 Tenant/Platform Config |
| 6 | Authentication & Roles | Partial | 6 | 1 Identity · 7 Roles & Permissions |
| 7 | Money Controls — Budgets + Limits + Pricing | Partial | 4 | 5 Limits · 6 Pricing |
| 8 | Notifications & Engagement | Planned | 3 | 13 Notifications · 17 Engagement Emission |
| 9 | Catalog Expansion — tiers/badges/challenges | Planned | 5 | 16 Rewards Catalog |
| 10 | Rules Engine Expansion — 7 rule types | Partial | 7 | 9 Rules Engine |
| 11 | Hot-path Balance & Ledger Partitioning | Planned | 6 | 3 Ledger |
| 12 | User Type Foundation | Shipped | 6 | 1 Identity |
| 13 | Admin User Creation & Type Management | Shipped | 5 | 1 Identity |
| 14 | External User-Creation API | Shipped | 7 | 1 Identity · 14 Tenant/Platform Config |
| 15 | Type-Aware Limits | Shipped | 5 | 5 Limits |
| 16 | Type-Aware Pricing | Shipped | 5 | 6 Pricing |
| 17 | Airtime Merchant Vertical | Shipped | 6 | 4 Payment Orchestration |
| 18 | N-Eyes Approval — Treasury & Admin Money Movements | Shipped | 6 | 7 Roles · 14 Config |
| 18S | External Partner Treasury — Fund / Withdraw | Shipped | — | 4 Payment · 14 Config |
| 19 | Charge Engine Foundation | Shipped | 4 | 6 Pricing |
| 20 | Charge Assembler & Ledger Integration | Shipped | 3 | 3 Ledger · 6 Pricing |
| 21 | Agent Cash-In Vertical | Shipped | 3 | 4 Payment Orchestration |
| 22 | Config Governance — Maker-Checker (Four-Eyes) | Shipped | 4 | 6 Pricing · 14 Config |
| 23 | Fail-Closed Service Gating | Shipped | 2 | 5 Limits · 6 Pricing |
| 24 | Pricing v2 Admin UI | Shipped | 3 | 6 Pricing · 14 Config |
| 25 | Pricing Admin Refinements | Shipped | 9 | 6 Pricing · 14 Config |
| 26 | Channel-Aware Money-Movement Controls | Planned | 6 | 4 Payment · 5 Limits · 7 Roles |
| 27 | Post-Registration Identifier Linking | Partial | 4 | 1 Identity |
| 28 | Instrument Creation Provisions System Wallets | Planned | 1 | 2 Account · 14 Config |
| A | Make deployment mode load-bearing | Shipped | 2 | 8 Event Ingestion · 14 Config |
| B | Internal wallet → rewards pipeline (`both` mode) | Partial | 8 | 9 Rules · 10 Reward Issuance |
| C | Mobile rewards visibility & celebration | Shipped | 5 | 16 Rewards Catalog |
| DASH | Analytics / KPI Dashboard | Shipped | 15 | (new) Analytics/Reporting |
| MOB | Mobile App (Expo) | Partial | 8 | 1 Identity · 4 Payment · 16 Catalog |
| HARD | Ledger / money-path hardening (cross-cutting) | Partial | 5 | 3 Ledger · 5 Limits |
| SEG | Customer Segmentation — Phase 1 (rules) + Phase 2 (AI, planned) | Partial | 12 | 16 Rewards Catalog · 14 Config |
| SEC | **External event-source authorization hardening** | Planned · **CRITICAL** | 6 | 8 Event Ingestion · 14 Tenant/Platform Config |
| VAPT | **Backend VAPT remediation (2026-08-21 sweep)** | Planned · **CRITICAL** | 13 | 1 Identity · 7 Roles · 11 Redemption · 14 Config |

**Totals:** 37 epics/initiatives · ~176 catalogued stories.

---

## Delivery snapshot

The platform is substantially built, not early-stage. The most-cited historical figure —
"~27% delivered, 25 of 93 stories" from `docs/LINEAR_BACKLOG.md` — is **stale and wrong**: it
predates the bulk of the work and only tabled Epics 1–17. Reconciled against the as-built code
and architectural memory, the real picture is:

- **Shipped and live** — the entire money spine (identity, accounts, append-only ledger, P2P,
  agent cash-in, subscriber cash-out, airtime, treasury); all seven rewards rule types; Keycloak
  admin auth, PIN/OTP user auth, HMAC callbacks and a per-user roles module; the full Pricing v2
  charge engine (slab fees, commission, tax) with fail-closed gating; three maker-checker
  governance subsystems (config four-eyes, treasury N-eyes, user-ops four-eyes) behind one unified
  `/approvals` inbox; the five user types with type-aware limits and pricing; the external
  partner API (keys + HMAC + rate limits) with fund/withdraw; a read-only per-currency analytics
  dashboard; mode-aware internal wallet→rewards wiring; and a working Expo mobile app covering
  auth, home, send, cash-in/out, airtime, and rewards.
- **Partial** — reconciliation (redemption sweep + UI shipped; a live provider status-poll and a
  dedicated redemption-sweep beat remain); the rewards pipeline's composite/nth-transaction
  counting is not yet fed by live transactions (Epic 10 / Epic B residual); reward-reversal
  claw-back is designed but not built (Epic B8); mobile flows are shipped but not every polish item
  is confirmed; step-up policy is fail-closed but not yet routed through config maker-checker.
- **Planned** — notifications (SMS/push) and external engagement emission (WebEngage) are
  topic-scaffolding only; catalog gamification (tiers/badges/challenges); reward budgets pre-issuance
  cap surface (budget model exists; the 50/80/100% alerting story is open); hot-path balance
  denormalisation + ledger partitioning (trigger-gated, pre-scale); channel-aware money controls;
  and system-wallet provisioning on new-instrument creation.
- **⚠ Open CRITICAL security finding (raised 2026-08-21)** — external event-source
  authorization. The HMAC integrity gate is not wired into the Kafka consumer, and the
  signing secret is optional at registration, so on the only production ingestion path a
  registered `source_key` — an identifier, not a credential — is the sole control between a
  Kafka message and minted points. Tracked as **Epic SEC**; nothing shipped against it.
- **⚠ Open CRITICAL/HIGH findings from the backend VAPT sweep (2026-08-21)** — a white-box
  review of the ledger, auth chain, redemption saga, partner API and FastAPI assembly. The
  money core came out clean (no double-spend, no lock-ordering defect, no missing tenant
  filter on user-facing queries); the exposure is on the **authorization boundary and the
  configuration surface** — the platform authenticates callers well and scopes them weakly.
  Two Critical (no admin↔tenant binding; `SIMULATOR_DEV_MODE=true` in the shipped template),
  three High, five Medium, three Low. Tracked as **Epic VAPT**; nothing shipped against it.

In short: the transactional and rewards core, the governance layer, and both frontends are
delivered; the remaining backlog is mostly engagement/notifications, gamification surfaces,
scale-hardening, and a handful of named wiring residuals.

---

# Epic → Story hierarchy

## Section 1 — Core Platform (Phases A–G)

### Epic 1 — Foundation (Identity + Accounts + Ledger) · **Shipped**
*Goal: the substrate — identity resolves any identifier to a canonical user; an append-only
double-entry ledger is the sole source of balance truth.*

- **1.1 User registration, multi-identifier** — register a user with ≥1 tenant-scoped identifier. *AC:* 201 returns the identifiers; duplicate within a tenant → 409; the same value in a different tenant is allowed; unknown tenant → 404; at least one identifier required. **Shipped**
- **1.2 Identifier resolution** — resolve any identifier to the canonical user in a tenant. *AC:* returns the user id; unknown → 404; a cross-tenant lookup → 404 with no existence leak. **Shipped**
- **1.3 Account model, core account types** — financial_wallet, points_account, and the system accounts (points issuance, provider redemption wallet, cash inflow float). *AC:* create + derived-balance read; cross-tenant read → 404; currency stored upper-cased; invalid type → 422. **Shipped**
- **1.4 Ledger service, double-entry** — one atomic posting service every money path calls. *AC:* ≥2 legs summing to zero (else 422); a single leg is rejected; idempotency per (tenant, key); a foreign account is rejected. **Shipped**
- **1.5 Append-only structural guarantee** — the ledger is never updated. *AC:* an invariant test asserts no mutable timestamp on ledger entries and that the whole system sums to zero. **Shipped**
- **1.6 Seed script + test users** — idempotent local seed. *AC:* a baseline tenant with two users' wallets/points plus a system issuance account; re-running is a no-op. **Shipped**

### Epic 2 — P2P Transfer · **Shipped**
*Goal: the first real money movement between users — overdraft-safe and concurrency-safe.*

- **2.1 Peer transfer + overdraft prevention** — user-to-user transfer by identifier. *AC:* Idempotency-Key required; self-transfer → 422; insufficient funds → 409; posts a balanced two-leg transaction. **Shipped**
- **2.2 Concurrent double-spend protection** — the sender's wallet is serialised. *AC:* two simultaneous full-balance transfers resolve to exactly one success and one 409. **Shipped**
- **2.3 Internal top-up + opening balances** — fund a wallet from the operator cash float. *AC:* debits the float, credits the wallet; the per-(tenant,currency) float is provisioned on demand; seeded opening balances are idempotent. **Shipped**

### Epic 3 — Kafka Rewards Inflow · **Shipped**
*Goal: external events drive rule evaluation and credit user points.*

- **3.1 Event source registration** — register an external event source. *AC:* create a source; duplicate source key → 409; field-mapping defaults applied; active by default. **Shipped**
- **3.2 Event ingestion, dedup + tenant scope** — ingest and normalise events. *AC:* an unregistered source is logged REJECTED; a duplicate (source, event id) is a DUPLICATE no-op; a tenant mismatch is REJECTED. **Shipped**
- **3.3 Rules engine: first_time + milestone** — the first two rule types. *AC:* first_time fires once per user; milestone counts to a threshold, fires, and resets; inactive rules are skipped; source-agnostic. **Shipped**
- **3.4 Reward issuance, double-issue protection** — credit points idempotently. *AC:* a uniqueness guard over (user, rule, triggering event) enforces once-only issuance; rejects a missing points/issuance account. **Shipped**
- **3.5 Rule CRUD admin endpoints** — manage rules. *AC:* create validates type-specific fields; list is tenant-scoped; an invalid config → 422. **Shipped**

### Epic 4 — Redemption + Catalog · **Shipped**
*Goal: convert points to cash via a provider and surface the full rewards story to the user.*

- **4.1 Provider registration** — register a redemption provider. *AC:* atomically creates the provider and its wallet; retry/escalation config stored; tenant-scoped. **Shipped**
- **4.2 Initiate redemption (two-legged PENDING)** — reserve points. *AC:* Idempotency-Key; locks, derives, and rejects on insufficient points; posts atomic PENDING legs; concurrent double-spend blocked; cross-tenant → 404. **Shipped**
- **4.3 Confirm (PENDING → COMPLETED)** — settle a redemption. *AC:* flips the legs; records reference + completion time; re-confirm → 409; cross-tenant → 404. **Shipped**
- **4.4 Fail (PENDING → REVERSED)** — reverse a redemption. *AC:* reason required; the reversal restores points (excluded from balance); confirm-then-fail → 409. **Shipped**
- **4.5 Catalog summary** — the user's points position. *AC:* available + reserved + lifetime earned/redeemed; a user with no points account returns `{points:null}` (not 404); all values ledger-derived. **Shipped**
- **4.6 Redemption history** — *AC:* newest-first, tenant-scoped, all statuses. **Shipped**
- **4.7 Points history (full audit trail)** — *AC:* every points-account entry; reward credits show rule name + event id; cross-tenant → empty. **Shipped**

### Epic 5 — Reconciliation + Admin UI · **Partial**
*Goal: close the stale-PENDING gap and give operators a UI.*
*Residual: a live provider status-poll (5.4) is not built; a dedicated redemption-sweep beat may still be manual (5.5).*

- **5.1 Sweep stale PENDING** — resolve stuck redemptions. *AC:* threshold sweep increments a retry counter and escalates to manual review at the ceiling; each item audited; terminal/recent items ignored. **Shipped**
- **5.2 Manual resolve from manual review** — operator override. *AC:* outcome + reason; COMPLETED/REVERSED flips applied; a non-manual-review item → 409; before/after audited. **Shipped**
- **5.3 Audit-log query** — *AC:* tenant-scoped, newest-first, page size capped. **Shipped**
- **5.4 Provider status-check polling** — real HTTP to the provider status URL, TLS 1.2+, HMAC-verified, auto-confirm/fail. **Planned** *(HMAC infra now exists; the poll itself is unbuilt).*
- **5.5 Scheduled sweep via Celery beat** — *AC:* periodic per-tenant sweep emitting metrics. **Partial** — a Celery beat exists (rewards recon sweep on a 60s beat, worker/beat/Flower in compose); a dedicated redemption-sweep beat may still be manual.
- **5.6 Admin UI shell** — app shell, Keycloak login, sidebar, command palette, tenant switcher, dark theme. **Shipped**
- **5.7 Admin operator screens** — users, transactions, reconciliation, audit (and many more). **Shipped**

### Epic 6 — Authentication & Roles · **Partial**
*Goal: Keycloak on admin, PIN/OTP for users, HMAC on callbacks, a per-user roles module.*
*Residual: a few legacy test-only endpoints intentionally retained (6.4); one known audit gap (6.6).*

- **6.1 Keycloak JWT validation** — admin auth dependency. *AC:* invalid/expired/`alg:none`/unknown-key/issuer-mismatch → 401; JWKS cached with a refetch floor; typed role checks. **Shipped**
- **6.2 PIN/OTP user auth flow** — OTP send/verify, set-PIN, PIN auth. *AC:* single-use hashed OTP + PIN; failed-attempt lockout; server-side sessions with sliding timeout. **Shipped**
- **6.3 Per-user Roles & Permissions (Module 7)** — role check as the first orchestration step. *AC:* an unpermitted action → 403; admin role CRUD. **Shipped** *(live roles: platform-admin, config-approver, user-approver, treasury-approver, standard_user, agent).*
- **6.4 Actor from token, not body** — resolve the acting principal from auth. *AC:* external/airtime paths derive actor from key/session. **Partial** — some legacy test-only endpoints (e.g. admin `POST /identity/users`) are intentionally kept for partner/seed/tests.
- **6.5 HMAC on provider callbacks** — signed inbound callbacks. *AC:* HMAC-SHA256, constant-time compare, ≤5-min replay window, failure → 401 + audit. **Shipped** *(airtime + external-API HMAC).*
- **6.6 Audit-log writes from every state-changing endpoint** — actor + IP + before/after. **Partial** — audit coverage is broad; a known gap is that external partner user-creation writes no audit row (see Conflicts §9).

### Epic 7 — Money Controls (Budgets + Limits + Pricing) · **Partial**
*Goal: pre-issuance / pre-ledger guards — reward budgets, transaction limits, fees.*
*Residual: the reward-budget pre-issuance alerting surface (7.1) is not built (the budget model + FOR-UPDATE cap check exist).*

- **7.1 Reward budgets + pre-issuance check** — cap issuance per (tenant, scope, currency, window). *AC:* an exceeded budget → 409; 50/80/100% alerts. **Planned** *(a budget model + windowed cap check exist and gate points issuance; the alerting surface is the open part).*
- **7.2 Limits & Thresholds (Module 5)** — per-type min/max + rolling caps before the ledger write. **Shipped** *(extended type-aware in Epic 15).*
- **7.3 Pricing Engine (Module 6)** — fee resolved before the ledger write and added as a debit leg; a zero fee is still an explicit checked config. **Shipped** *(extended in Pricing v2, Epics 19–24).*
- **7.4 Admin UI for limits + pricing** — editable per-tenant tables, audited on save. **Shipped**

### Epic 8 — Notifications & Engagement · **Planned**
*Goal: internal SMS/push plus outbound engagement events.*

- **8.1 Transaction-completion notification** — Pay-PRD-0810/0840. **Planned**
- **8.2 Reward-issuance notification** — Pay-PRD-0830. **Planned** *(an in-app mobile celebration overlay exists via Epic C; SMS/push are not built).*
- **8.3 Outbound engagement emitter** — emit reward.issued / tier.changed / streak.broken / milestone.approaching to an engagement platform. **Planned** *(topics are declared in config but no producer emits — see Section 7, Module 17).*

### Epic 9 — Catalog Expansion · **Planned**
*Goal: gamification surfaces beyond summary/history.*

- **9.1 Tier status + auto-progression** · **9.2 Badges (earned/locked)** · **9.3 Active challenges** · **9.4 Next-milestone nudges** · **9.5 Points-expiry warnings** — all **Planned** *(9.5 is a Phase-1 PRD non-goal).*

### Epic 10 — Rules Engine Expansion · **Partial**
*Goal: the remaining rule types beyond first_time/milestone, plus multipliers and segments — completing all seven PRD rule types.*
*Residual: the evaluator's composite-count and referral nth_transaction paths are not yet fed by live transactions (see below).*

- **10.1 Streak** (WAL-73) — fires on N consecutive day/week periods. **Shipped**
- **10.2 Value-based** (WAL-74) — fires on any single event ≥ a minimum amount. **Shipped**
- **10.3 Composite AND/OR** (WAL-75) — ≥2 sub-conditions combined with AND/OR. **Shipped**
- **10.4 Campaign** (WAL-76) — date-gated first-time semantics. **Shipped**
- **10.5 Referral** (WAL-77) — code-at-signup attribution; configurable trigger (signup / nth_transaction); both-sided reward as points or ZAR cashback (cap-exempt); rewards only when a code was used. **Shipped**
- **10.6 Bonus multipliers** (WAL-78) — a multiplier applied to points issuance before the budget check. **Shipped**
- **10.7 Segment binding + segments module** (WAL-79) — bind a rule to an admin-assigned cohort. **Shipped**
- **Residual (pipeline wiring):** internal transactions now feed the evaluator via the Epic B outbox, but external events are not persisted as `transactions`, so composite counts and referral `nth_transaction` counts sourced from external events can read zero. The logic is unit-tested and forward-compatible; wiring counts to the live transaction stream is the open item. **Partial**

### Epic 11 — Hot-path Balance & Ledger Partitioning · **Planned**
*Goal: a denormalised live balance + monthly partitioning before first real-tenant onboarding. Trigger-gated (build when a balance read exceeds ~50ms, any account exceeds ~10k entries, a history drop is planned, or onboarding is imminent).*

- **11.1 Live balance columns on accounts** — authoritative for user wallets, advisory for system accounts; idempotent backfill. **Planned**
- **11.2 Atomic write-path refactor** — overdraft-check-and-insert in one transaction; reserved balance tracked across PENDING transitions; the concurrency test still passes. **Planned**
- **11.3 Drift-detection invariant + daily job** — compares the column to the ledger sum; a mismatch is a P0 audit + alert; never auto-corrects. **Planned**
- **11.4 Monthly partitioning of ledger entries** — rolling window with verified pruning. **Planned**
- **11.5 Partition-drop runbook + archive summaries** — idempotent dry-run archive + runbook. **Planned**
- **11.6 Mobile balance read uses the denormalised column** — sub-20ms at scale; result matches the derived balance. **Planned**

---

## Section 2 — User-Types Initiative (Epics 12–17)
*Five user types — consumer / agent / super_agent / merchant / head_merchant — driving type-aware
pricing/limits, admin + external user creation, and the first merchant vertical. The whole
initiative is implemented on `main`.*

### Epic 12 — User Type Foundation · **Shipped**
- **12.1 user_type enum + column + backfill** — five types, default consumer, backfilled + indexed. **Shipped**
- **12.2 Parent hierarchy validation** — agent→super_agent, merchant→head_merchant, same tenant; a bad pairing → 422. **Shipped**
- **12.3 Expose type + parent in identity schemas** — round-trippable, backwards-compatible. **Shipped**
- **12.4 Change-type endpoint + audit + idempotency** — platform-admin; mandatory reason; leaving merchant blocked while a collection balance is non-zero; entering merchant needs a profile; emits a type-changed event. **Shipped**
- **12.5 User lifecycle topic + user.created/type_changed events** — keyed on user id; emitted after commit; idempotent consumer. **Shipped**
- **12.6 PRD Module 1 + glossary update** — documents the five types, the hierarchy, and the change flow. **Shipped**

### Epic 13 — Admin User Creation & Type Management · **Shipped**
*Note: superseded by the four-eyes `user_operations` flow — admin create/edit-user now propose→approve (platform-admin maker, user-approver checker). The old direct dialogs/actions are orphaned and queued for deletion (see Conflicts §8).*

- **13.1 Harden admin create-user (identifier, type, parent, merchant profile)** — ≥1 identifier required; audited; idempotent. **Shipped**
- **13.2 Admin create-user dialog** — now the propose dialog. **Shipped**
- **13.3 Change-type action + reason modal** — surfaces transition-blocked / invalid-parent; now via the edit propose flow. **Shipped**
- **13.4 User-type badge + filter on the list** — **Shipped**
- **13.5 Server actions + API client wiring** — **Shipped** *(old direct create/change-type actions now orphaned).*

### Epic 14 — External User-Creation API · **Shipped**
*Per-tenant API keys + HMAC signing, rate-limited, idempotent, tenant-derived-from-key; security-reviewed.*

- **14.1 API keys model** — public key id, encrypted secret shown once, status, last-used; tenant-scoped. **Shipped**
- **14.2 API key management UI** — create (show once) / list / revoke on a dedicated screen. **Shipped**
- **14.3 API-key + HMAC auth dependency** — verifies key + signature within a replay window; resolves the tenant. **Shipped**
- **14.4 External create-user endpoint** — tenant from the key, never the payload; mass-assignment blocked (a partner cannot set user_type/parent/verified); reuses the identity create path. **Shipped**
- **14.5 Per-key rate limiting** — a token-bucket cap; exceeding → 429. **Shipped**
- **14.6 Curated external OpenAPI + exported partner spec** — **Shipped**
- **14.7 Security review (STRIDE + OWASP API)** — threat model produced; high/medium findings fixed. **Shipped** *(deferred hardening items + the partner-create audit gap tracked in the threat model — see Conflicts §9).*

### Epic 15 — Type-Aware Limits · **Shipped**
- **15.1 Nullable user_type on limit + wallet-limit configs** — uniqueness extended for the type dimension. **Shipped**
- **15.2 Resolution precedence** — an exact type beats the NULL default. **Shipped**
- **15.3 CRUD schema + router for user_type** · **15.4 UI column + selector ("All types" when NULL)** · **15.5 Precedence-matrix tests** — **All Shipped**

### Epic 16 — Type-Aware Pricing · **Shipped** *(mirrors Epic 15 for fees)*
- **16.1 Nullable user_type on pricing configs** · **16.2 Fee-quote precedence** · **16.3 CRUD schema/router** · **16.4 UI column + selector** · **16.5 Precedence tests** — **All Shipped**

### Epic 17 — Airtime Merchant Vertical · **Shipped**
*A merchant collects user funds into a collection account and provisions airtime via a provider after commit.*

- **17.1 Merchant profiles model** — 1:1 with merchant users; provider config. **Shipped**
- **17.2 Merchant collection account + provisioning** — one per (tenant, merchant, currency). **Shipped**
- **17.3 Airtime purchase flow** — debit the consumer wallet, credit the collection account, fee legs; type-aware limits; a PENDING recharge; Idempotency-Key. **Shipped**
- **17.4 Provider adapter + provisioning after commit** — a simulator provider with driveable outcomes; the live provider is stubbed to raise; the external call is never inside the transaction. **Shipped**
- **17.5 Failure reversal + reconciliation hook** — appends a reversal (append-only); a stuck PENDING surfaces in reconciliation for admin resolve. **Shipped**
- **17.6 Events + ledger-invariant tests** — sum-to-zero, append-only, reversal, idempotency, isolation. **Shipped** *(a client webhook is deferred to a future partner-API airtime endpoint).*

---

## Section 3 — N-Eyes Approval & External Treasury (the Epic-18 pair)

### Epic 18 — N-Eyes Approval for Treasury & Admin Money Movements · **Shipped**
*Goal: high-value money operations require four-eyes (maker + 1) or six-eyes (maker + 2 distinct),
configurable — generalising the config maker-checker (Epic 22) to money operations. In scope:
bank-float create/remove and admin fund/withdraw of a user wallet. Out of scope: partner-API
fund/withdraw (those stay direct but must still satisfy the ledger invariants — see Epic 18S).*

- **18.1 Approval-policy model + configurable eyes** — required approvals ∈ {1,2}; default four-eyes; no self-approval; six-eyes approvers must be distinct; a policy change is audited. **Shipped**
- **18.2 Money-operation request + N-approval state machine** — PENDING → APPROVED → APPLIED | CHANGES_REQUESTED | WITHDRAWN | REJECTED; the apply on final approval is idempotent; every action audited. **Shipped**
- **18.3 Route bank-float create/remove through approval** — applied only at quorum; invariants preserved. **Shipped**
- **18.4 Route admin fund/withdraw through approval** — a proposal, not an immediate write; ledger invariants enforced at apply; distinct from the partner-API path. **Shipped**
- **18.5 Admin UI: money-op approval queue + N-eyes progress** — "1 of 2 approvals", role-gated, never one's own request. **Shipped** *(now folded into the unified `/approvals` page).*
- **18.6 Audit + full test matrix** — every transition audited; no double-apply; tenant-isolated; ledger invariants hold. **Shipped**

### Epic 18S — External Partner Treasury: Fund / Withdraw · **Shipped**
*(Historically numbered "Epic 18" in the threat model — relabelled 18S here to resolve the number
collision; see Conflicts §1.)*
*Goal: a partner moves real money on a user wallet over the Epic-14 API-key + HMAC surface —
partner fund (reuses top-up) and withdraw (reuses treasury core, supports withdraw-all). Tenant
derived from the key; user by identifier; the partner Idempotency-Key is the ledger key; type-aware
limits (a partner is less trusted than an operator); audited.*

- **Status:** **Shipped** — the ship-blocking lock ordering was fixed (lock moved to the caller + counter-account pre-created); the max-balance race was closed and the amount bounded. The mandatory funding-ceiling on partner fund is a **product decision to fail-OPEN** (accepted, not implemented) — a partner fund may legitimately push a wallet past its max-balance. Remaining medium/low findings are pre-go-live hardening. **This is a distinct feature from Epic 18 despite the shared historical number.**

---

## Section 4 — Pricing v2 Initiative (Epics 19–24) · **all Shipped**
*Slab fees, agent commissions, taxes, cash-in, and config governance.*

### Epic 19 — Charge Engine Foundation · **Shipped**
- **19.1 Commission + tax system account types** · **19.2 Slab fees on pricing configs (amount bands + resolution)** · **19.3 Commission configs + calculation** · **19.4 Tax configs + calculation** — additive and back-compatible. **All Shipped**

### Epic 20 — Charge Assembler & Ledger Integration · **Shipped**
- **20.1 Charge assembler (inclusive/exclusive matrix → balanced legs)** · **20.2 Commission + tax amounts on the transaction** · **20.3 Commission credit is cap-exempt at the balance guard** — **All Shipped**

### Epic 21 — Agent Cash-In Vertical · **Shipped**
- **21.1 Cash-in service catalog + agent role permission** · **21.2 Cash-in module: agent deposit → customer wallet** · **21.3 Cash-in E2E + ledger-invariant + load tests** — **All Shipped**

### Epic 22 — Config Governance: Maker-Checker (Four-Eyes) · **Shipped**
- **22.1 Config-approver role + self-approval-forbidden** · **22.2 Config change-request + review models** · **22.3 Maker-checker endpoints + revise/resubmit loop** · **22.4 Route config creation through approval; retire direct create/delete** — **All Shipped** *(the revise-scope trust-boundary gap is resolved — revise now re-validates tenant + scope like propose).*

### Epic 23 — Fail-Closed Service Gating · **Shipped**
- **23.1 Pricing-and-limits guard** — a service executes only if BOTH a pricing config AND a limit config resolve for the acting user's type, else 422 before any ledger write; unconditional (not flag-gated). **Shipped**
- **23.2 Remove fail-open swallows; wire the gate into every money path** — no silent zero-fee / limitless pass-through. **Shipped**

### Epic 24 — Pricing v2 Admin UI · **Shipped**
- **24.1 Pricing dialog: slab bands + fee-inclusive + per-band preview** · **24.2 Commission-config + tax-config screens** · **24.3 Config-request review UI (maker submit + checker thread)** — **All Shipped** *(frontend automated tests deferred per repo policy at the time; verified via typecheck/build/review).*
> **Deferred (Phase 2):** commission hierarchy roll-up across the parent chain (the schema already supports it).

---

## Section 5 — Later Config & Identifier Epics (25–28)

### Epic 25 — Pricing Admin Refinements · **Shipped**
*Goal: polish the pricing/config admin — multi-band validation, config-type filtering, and a shared read-only detail view. Confirmed by the as-built admin UI (grouped multi-band pricing/commission tables, a shared config-detail/compare view, and inline changes-requested sections).*

- **25.1 Multi-band payload validation (propose)** · **25.2 Multi-band apply (all-or-none)** · **25.3 config_type filter on config-requests** · **25.4 Type/lint/suite gate** · **25.5 Pricing menu parent + relabel** · **25.6 Shared read-only config-detail view** · **25.7 Approval drawer via config-detail; drop JSON revise** · **25.8 Multi-band create dialogs + revise mode** · **25.9 Native pages: changes-requested section + view action** — **All Shipped**

### Epic 26 — Channel-Aware Money-Movement Controls · **Planned**
*Goal: two-channel containment for fund/withdraw — the ADMIN channel gets dynamic approval
escalation (count-based + amount-based tiers, ceiling raised to 3 approvals); the API channel gets
hard per-key velocity limits (no approval); plus a channel allow-list. Record the actor
(channel / initiator type / initiator id) on every transaction. Decisions: daily window;
per-specific-key velocity; count only APPLIED operations; fund + withdraw are the must-haves;
the allow-list is in scope.*

- **26.1 Data foundation** — add channel / initiator type / initiator id to transactions, threaded from both routers through the ledger. **Planned**
- **26.2 Channel allow-list** — a shared pre-ledger guard + per-service channel policy; reject a disallowed channel. **Planned**
- **26.3 API velocity limits** — per-key channel caps in the limits check (leaked-key containment). **Planned**
- **26.4 Amount-based approval** — amount-tier resolution at propose; ceiling → 3. **Planned**
- **26.5 Count-based approval** — a daily rolling count tier (APPLIED-only) keyed on the initiator. **Planned**
- **26.6 Admin UI** — approval-config ladders (count + amount with currency), a per-key velocity screen, an allow-list matrix. **Planned**

### Epic 27 — Post-Registration Identifier Linking (account / card) · **Partial**
*Goal: add identifiers to an existing user after registration (registration itself deliberately
requires a contactable phone/email).*
*Residual: the admin "Add identifier" action is partially surfaced (27.2); verification + card tokenisation are unbuilt (27.3, 27.4).*

- **27.1 Add-identifier endpoint (existing user)** — admin + partner-API; an account number is stored unverified; a uniqueness clash → 409; audited; a card is rejected here. **Shipped**
- **27.2 Admin "Add identifier" action** — type phone/email/account_number; shows verified state. **Partial** *(add-identifier + a manual account-number verify button exist; full flow polish pending).*
- **27.3 account_number verification flow** — flip unverified → verified via micro-deposit / partner confirm (platform-admin gated). **Planned** *(a manual admin-verify affordance exists; the automated verification flow is queued).*
- **27.4 Card tokenisation (PCI)** — tokenise via a PSP, store the token only, never the PAN. **Planned — Phase 2** *(blocked on PSP selection).*

### Epic 28 — Instrument Creation Provisions System Wallets · **Planned**
*Goal: creating a new instrument (currency) must also provision that currency's system accounts,
not just user wallets. (Tenant-level baseline provisioning already shipped via the tenant
provisioning work; this extends it to the per-instrument create path.)*

- **28.1 Provision system accounts on instrument create** — a financial currency provisions its system accounts (cash inflow, fee, commission, tax), a points currency its issuance account; idempotent; audited; the new currency appears in System Wallets with zero balances. **Planned**

---

## Section 6 — Mode-Aware Rewards + Mobile Visibility (Epics A/B/C)
*Gated by the tenant's `business_type` (wallet | rewards | both), now load-bearing. Shipped
2026-08-03, with one designed-not-built residual (B8).*

### Epic A — Make deployment mode load-bearing · **Shipped**
- **A1 Business-type constants + single resolver** — one module answers "is wallet→rewards enabled" (both) and "are external events allowed" (rewards). **Shipped**
- **A2 External events restricted to `rewards` tenants** — a non-rewards tenant's external event is rejected and audit-logged (wrong mode). **Shipped**

### Epic B — Internal wallet → rewards pipeline (`both` mode) · **Partial**
*A completed rewardable wallet transaction durably drives rule evaluation + issuance,
reconcilable and reversal-ready — closing the historical evaluator-not-wired gap.*
*Residual: reversal claw-back (B8) is designed, not built.*

- **B1 Reward outbox table + seen-at + migration** — status/attempts/last-error/transaction id; a (tenant, status) index. **Shipped**
- **B2 Reward trigger on the transaction request** — an optional trigger whose presence opts a transaction into rewards. **Shipped**
- **B3 Outbox written atomically with the ledger** — only in `both` mode and only for rewardable types (p2p, cash_in, cashout, airtime_recharge); no row in wallet mode; no row without a trigger (loop avoidance). **Shipped**
- **B4 Shared evaluate-and-issue core** — both the Kafka path and the outbox path call the same core; idempotent via the reward-events unique index. **Shipped**
- **B5 Outbox drainer + immediate post-commit attempt** — drains the user's pending rows in a fresh session; idempotent; absolutely fail-open (never raises onto the money path). **Shipped**
- **B6 Celery reconciliation sweep** — drains pending/retryable rows across tenants on a 60s beat. **Shipped**
- **B7 Money paths trigger rewards + inline earned points** — p2p / cash_in / cashout / airtime set the trigger and attempt an immediate post-commit issue; the response returns post-multiplier earned points; cash-in rewards the customer; airtime fires on successful-vend completion. **Shipped**
- **B8 Reversal claw-back hook** — the outbox retains the transaction id; a future claw-back is documented and a skipped test records the intent. **Planned** *(designed, not built).*
> **Go-live caveat (from the plan):** there is no new flag — existing `both` tenants begin issuing wallet-driven rewards the moment Epic B deploys. Confirm the intended go-live before B7.

### Epic C — Mobile rewards visibility & celebration · **Shipped**
- **C1 Rewards read endpoint (catalog + progress + recent)** — disabled for wallet mode; else the active-rule catalog for the user's segment with per-rule progress + status, plus recent earned rewards with a seen flag; auth + isolation tested. **Shipped**
- **C2 Mark-seen endpoint (one-shot)** — sets seen on the caller's own events; idempotent. **Shipped**
- **C3 Mobile rewards API client** — typed getRewards / markRewardsSeen. **Shipped**
- **C4 Mobile rewards screen + home tile** — an empty state when disabled; catalog cards with progress bars; a recent list. **Shipped**
- **C5 Reward celebration graphic** — a one-shot overlay on unseen rewards, then mark-seen + invalidate; gated on enabled. **Shipped**

---

## Section 7 — Cross-cutting shipped initiatives (unnumbered)

### DASH — Analytics / KPI Dashboard · **Shipped**
*An interactive per-currency KPI dashboard backed by a read-only analytics backend module
(tenant-scoped GET aggregates over existing tables, no writes).*
*Residual: a new-vs-returning users metric is deferred.*

- **Backend:** summary, service-mix, status, users (incl. DAU/WAU/MAU), revenue, rewards, liquidity/net-flow, and user-type aggregates; a bad range/granularity → 422. **Shipped**
- **Frontend:** stat tiles + time-range switcher; trend / service-mix / status / users / revenue / rewards / liquidity / user-type charts; a "needs attention" strip; a currency toggle. **Shipped**
- **Hard invariant:** money is **never** summed or converted across currencies — every money metric is grouped and returned per-currency. **Revenue = operator fee only** (tax pass-through + agent commission cost excluded). **Shipped**

### MOB — Mobile App (Expo) · **Partial**
*Eight phases A–H. Backend URL comes from the EAS "preview" remote env var; the simulator uses
localhost loopback. Repo policy: no EAS/mobile builds unless explicitly requested.*
*Residual: some later send/deposit/withdraw polish is shipped but not every item is confirmed.*

- **Phase A — Backend additions** (auth-start phone lookup, demo top-up, earned-points on the P2P response, catalog/featured, seed enrichment). **Shipped**
- **Phase B — Bootstrap** (Expo, theme + fonts, brand assets, router, secure storage/session, env config, API client, query cache). **Shipped**
- **Phase C — Auth flow** (phone, OTP, set-PIN, PIN + biometric slot); create-account self-registration with a referral code + refer-a-friend card. **Shipped**
- **Phase D — Home + Activity + Profile** (tab bar, balance cards, quick actions, activity). **Shipped**
- **Phases E–H — Send-money, rewards, deposit/withdraw, polish** — **Partial** *(P2P, cash-in, cash-out, airtime, and the rewards screen + celebration are shipped; some polish and a known multi-currency display bug on the P2P success screen remain).*

### HARD — Ledger / money-path hardening (cross-cutting invariants) · **Partial**
*Residual: step-up policy is fail-closed but not yet routed through config maker-checker (Part 2); the unified `/approvals` UI shipped but a couple of backend follow-ups were still open at the time.*

- **Cash-float floored** — the operator cash float is overdraft-floored at the choke point; funding fails if the float is empty (a distinct 409) and must be pre-funded from the bank. **Shipped**
- **Money-path lock continuity** — the FOR UPDATE wallet lock is centralised in the ledger balance guard (per-service locks removed; redemption keeps its own points-account lock); all accounts pre-exist and no commit intervenes before the guarded commit. **Shipped**
- **user.status enforced** — the admin access-lock (login-lock / transaction-lock) now enforces user status (was cosmetic); a status gate guards all money paths; separate from the PIN lockout. **Shipped**
- **Step-up fail-closed (Part 1)** — a transaction over the configured threshold requires a PIN, and with no policy a PIN is always required. **Shipped**. **Part 2 (route the step-up policy through config maker-checker as a `step_up` config type)** — **Planned**.
- **Unified Approvals page** — one role-gated `/approvals` inbox aggregating the Configuration / Transactions / Users maker-checker queues. **Shipped** *(step-up slots into the Configuration tab once it becomes a config type).*

### SEG — Customer Segmentation · **Partial** *(Phase 1 shipped, Phase 2 planned)*
*Tenant-scoped customer segments — a `segment_groups` → `segments` hierarchy (e.g. Engagement,
Transaction Value, Customer Loyalty), each dynamic segment carrying a JSON criteria DSL evaluated
by a batch job against a registry of 9 wallet-attributed metrics. Design:
[`docs/superpowers/specs/2026-08-12-ai-segmentation-design.md`](superpowers/specs/2026-08-12-ai-segmentation-design.md).*

- **Groups + dynamic segments** — `segment_groups` and `segments` models (tenant-scoped, `is_system` seed tiers protected from delete), group CRUD API, and a segment CRUD/list/preview API. **Shipped**
- **Criteria DSL (v1)** — a versioned JSON AND/OR condition tree over 9 metrics (`txn_count`, `txn_sum`, `wallet_balance`, `points_balance`, `points_redeemed`, `rewards_earned`, `account_age_days`, `days_since_last_txn`, `referral_count`), each with a single-source-of-truth registry entry (SQL builder + schema enum + AI-prompt vocabulary). **Shipped**
- **Wallet-attribution decision** — `txn_count`/`txn_sum`/`days_since_last_txn` are attributed to the wallet account touched by a COMPLETED transaction (either ledger leg), not `Transaction.initiated_by`, so a P2P recipient and a cash-in-funded customer are correctly counted, not just the initiating agent. **Shipped**
- **Batch evaluator** — Celery beat recomputes every tenant's dynamic segments hourly (`segments.recompute_all`); an admin-triggered manual recompute (`segments.recompute_tenant`, 202-accepted) is also enqueued from the API for immediate refresh after a criteria edit. **Shipped**
- **Seeded default tiers** — 3 system groups × 3 tiers each (Engagement: Dormant/New/Active; Transaction Value: Low/Mid/High; Customer Loyalty: Bronze/Silver/Gold) ship via `make seed`. **Shipped**
- **Admin UI** — a group-sectioned `/segments` page with a criteria builder dialog (metric/operator/value rows, AND/OR composition, live match-count preview) and a manual "Recompute now" action. **Shipped**
- **AI layer (Phase 2)** — natural-language → criteria DSL generation, reviewed before save. **Planned**; see the design doc above.

### SEC — External event-source authorization hardening · **Planned** · ⚠ **CRITICAL**
*Raised 2026-08-21 from a code read of the Kafka ingestion path. The five gates in
`process_external_event` — source registered → tenant scope → deployment mode → HMAC → dedup —
are correctly built and correctly ordered, and the HMAC primitive itself is sound (300s replay
window, constant-time compare, Fernet-encrypted secret at rest, rotation-friendly multi-`v1=`).
The problem is wiring, not cryptography: **the only path that carries production traffic — the
Kafka consumer — never supplies the raw bytes or the signature**, so the integrity gate is inert
there. A registered `source_key` is an identifier, not a credential; with signature verification
bypassed it is the sole control between a Kafka message and minted points.*
*Blast radius: anyone who can reach the broker and knows one registered `source_key` can mint
points for any user in that source's tenant, in any amount. Points convert to fiat through
internal redemption (Module 11b), so this is a money-loss path, not a data-integrity nuisance.*

- **SEC.1 — Kafka consumer must actually verify the HMAC signature** · **Critical** —
  `scripts/run_consumer.py:63` calls `process_external_event(session, event)` with neither
  `raw_body=` nor `signature_header=`, and never reads `msg.headers()`. Gate 4 therefore has
  exactly two behaviours and neither is "verify": a source **with** a secret rejects every message
  as `integrity_check_missing` (fail-closed, but the Kafka path is dead), and a source **without**
  one skips verification entirely and issues the reward. *AC:* the producer sets
  `X-Sasai-Signature` as a Kafka message header; the consumer passes `msg.value()` as `raw_body`
  and that header through to the pipeline; a valid signature is PROCESSED, a forged one REJECTED +
  audited, a missing one REJECTED; consumer-level tests cover all three (today there are none —
  HMAC is only tested on the HTTP `/external` and `/sim-ingest` routes);
  `/events/sim-kafka-produce` signs its payload the same way; and
  `docs/security/threat-models/phase-f5-hmac-and-audit.md` (§ "Kafka consumer … enforces HMAC",
  and the claim that the consumer receives the raw payload bytes) is corrected — both statements
  are currently false. **Planned**

- **SEC.2 — `shared_secret` must be mandatory on event-source registration** · **Critical** —
  the secret is optional in the admin dialog ("HMAC shared secret (optional, ≥ 32 chars)") and in
  `SourceRegistrationRequest`, which sets no minimum length at all. Registering a source without
  one is a single click and produces exactly the source that accepts unsigned events, because
  `process_external_event` skips gate 4 entirely when `shared_secret_encrypted IS NULL`. *AC:*
  the secret is required with a ≥32-char minimum in both the Pydantic schema and the dialog;
  registration without one → 422; the NULL-means-skip branch is removed so a legacy source with no
  secret rejects every event rather than trusting it; `seed.py` and any existing rows are migrated
  or explicitly deactivated. This is the story with teeth — SEC.1 is only meaningful once no
  source can opt out. **Planned**

- **SEC.3 — Event sources need list / deactivate / rotate** · **High** — the backend exposes only
  `POST /events/sources`, so `/events` in the admin UI renders an empty state ("Source list view
  ships in Phase G"). Operators cannot see which sources exist, which have a secret configured, or
  turn one off; flipping `status` to `inactive` or rotating a leaked signing key currently means a
  direct DB write or a `seed.py` re-run. For a credential that mints money, create-only with no
  revoke is the larger operational exposure. *AC:* `GET /events/sources` (tenant-scoped),
  `PATCH /events/sources/{id}` for status, and a rotate-secret endpoint that accepts a new secret
  and keeps the old one valid for one replay window; the admin table shows name, key, status,
  secret-configured, created-at, and last-event-seen; every action audit-logged. **Planned**

- **SEC.4 — Event-source registration must go through maker-checker** · **High** — pricing,
  limits, wallet limits, commissions, taxes, step-up and conversion rates all route through the
  config-request four-eyes pipeline. Registering an event source does not: one `platform-admin`
  creates a live points-minting channel in one dialog with no second approver, which is a weaker
  control than the one guarding a fee change. *AC:* `event_source` becomes a config type in the
  config-request registry; create / deactivate / rotate all land in the Configuration tab of
  `/approvals` and require a distinct approver; the direct `POST` is removed or restricted.
  **Planned**

- **SEC.5 — `source_key` uniqueness should be tenant-scoped** · **Low** — the column is
  `unique=True` globally rather than unique per tenant, so tenant A cannot register a key tenant B
  already holds, and the resulting `source_key_taken` 409 confirms to A that some other tenant has
  it — a small cross-tenant existence leak through a namespace the tenants do not share. *AC:*
  uniqueness moves to `(tenant_id, source_key)`; source lookup at ingestion resolves on the pair
  rather than the key alone; a migration handles existing rows; a cross-tenant registration of the
  same key succeeds. **Planned**

- **SEC.6 — Kafka broker has no authentication or ACLs** · **Critical for any shared environment**
  — `sasai-wallet-infra/docker-compose.yml` runs `PLAINTEXT` with no SASL and no ACLs
  (`KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"` is the only hardening). Acceptable for a laptop;
  it means that outside local dev, "authorization" on the event channel reduces to network
  reachability, and it is what turns SEC.1/SEC.2 from a defence-in-depth gap into a live one.
  *AC:* SASL_SSL (or mTLS) on the broker with a distinct principal per producer, per-topic ACLs
  restricting `wallet.events.external` writes to registered sources, TLS 1.2+ in transit per
  NFR-0260, and no credential in the compose file — this is a prerequisite for any non-local
  deployment, not a follow-up to it. **Planned**

### VAPT — Backend security sweep remediation · **Planned** · ⚠ **CRITICAL**
*White-box VAPT of `backend/app/**`, `scripts/` and `sasai-wallet-infra/` on 2026-08-21. Mobile
was out of scope. Every item below was verified by reading the code path, not inferred from a
design doc.*
*Two things the sweep checked and did NOT find, recorded so nobody re-opens them speculatively:
there is **no** double-spend or lock-ordering defect in `post_transaction` (locks taken in
canonical account-id order before any balance read, held through commit), and **no** missing
`tenant_id` filter on user-facing domain queries. The concurrency work is sound. The findings
below are almost all authorization and configuration, not arithmetic.*
*Event-source authorization is tracked separately as **Epic SEC** and is not duplicated here.*

- **VAPT.1 — Bind admin principals to tenants** · **Critical** — `AdminPrincipal` carries no
  tenant, `require_admin_role` checks only a realm-role string, and every admin money endpoint
  reads `tenant_id` straight from the request body (`treasury/router.py` fund / withdraw /
  adjust-system-wallet). Queries are tenant-filtered, but by a tenant the caller chose — that is
  scoping, not isolation, and the F.3 threat model's "mitigated" rating for tenant isolation does
  not hold for admin principals. Any `platform-admin` can act on any tenant by editing one field;
  maker-checker and audit narrow this but the platform cannot currently express a tenant-restricted
  operator at all. *AC:* `AdminPrincipal.tenant_ids` populated from a Keycloak claim; a single
  `require_tenant_access(tenant_id)` dependency on every admin route (one auditable check, not
  thirty inline ones); a distinct `platform-superadmin` role for genuinely global operations; a
  test asserting an admin scoped to tenant A gets 403 naming tenant B on `/treasury/fund`.
  **Planned**

- **VAPT.2 — `SIMULATOR_DEV_MODE` must default to false** · **Critical** —
  `backend/.env.example:22` ships `SIMULATOR_DEV_MODE=true` and `CLAUDE.md` tells operators to
  `cp .env.example .env`. The flag exposes `POST /events/sim-kafka-produce` (**no auth at all** —
  an unauthenticated write primitive onto the reward event bus), `POST /events/sim-ingest` (no
  admin auth), and `GET /events/sim-bootstrap` (**no auth** — returns every registered phone
  number mapped to its user UUID, a bulk PII disclosure against NFR-0240). Chained with SEC.1 this
  is a complete unauthenticated points-minting path: enumerate user ids, then produce events for
  them. The in-file comment warning against production use is documentation, not a control.
  *AC:* template default flipped to `false`; `Settings` refuses to boot when the flag is true and
  the environment is not `local`; the sim router is registered conditionally in `main.py` rather
  than flag-checked inside each handler; `sim-bootstrap` requires admin auth and masks identifiers
  even in local mode. **Planned**

- **VAPT.3 — Verify the JWT audience claim** · **High** — `auth/tokens.py` passes
  `"verify_aud": False`, annotated `# Phase F.4`; F.4 shipped and the setting never changed.
  Signature, `exp`, `iss` and an RS256 allowlist are all correctly enforced, so the token is
  genuinely realm-issued — but nothing checks it was issued for this backend, and realm roles are
  shared across every client in the realm. A token minted for any other realm client authenticates
  against the money API, widening VAPT.1's blast radius. *AC:* `verify_aud: True` with
  `audience=settings.KEYCLOAK_CLIENT_ID`; the Keycloak audience mapper added to
  `bootstrap_keycloak.py` **in the same change** (Keycloak omits `aud` without it, so flipping the
  flag alone locks out every admin); `azp` checked as a fallback where `aud` can't be relied on.
  **Planned**

- **VAPT.4 — Points must be whole units and rounding must not favour the redeemer** · **High** —
  `quote_fiat_amount` quantizes to 0.01 with `ROUND_HALF_UP`, and `InternalRedemptionRequest`
  constrains `points_amount` only to `gt=0` — no minimum, no integer constraint, backed by a
  `Numeric(20, 6)` column. Any redemption whose true value lands in `[0.005, 0.01)` rounds up to a
  full cent, so at a plain 100 PTS = 10 ZAR rate, twenty 0.05-point redemptions pay 0.20 ZAR
  against a true value of 0.10. The Pay-PRD-1295 anti-drain caps set a per-transaction *maximum*
  and are silent on minimums, and nothing rate-limits the endpoint (VAPT.9). Each redemption is
  individually well-priced and correctly ledgered, so aggregate reporting will not show it.
  *AC:* points constrained to whole units at the schema boundary plus a DB CHECK;
  `min_points_per_txn` added to `points_conversion_rates` and enforced fail-closed at the same call
  site as the max caps; quantize changed to `ROUND_DOWN`; `fiat_amount <= 0` rejected before the
  burn so the degenerate case 422s cleanly instead of burning-then-unwinding; a reconciliation
  query run over existing `internal_redemptions` to establish whether this has already been
  exercised. **Planned**

- **VAPT.5 — Session lifecycle: evict on re-auth, cap absolute lifetime** · **High** —
  NFR-0280 ("a new session on the same channel invalidates the earlier session") is not
  implemented: `create_session` has exactly one caller and never invalidates prior sessions, and
  `invalidate_user_sessions` is reached only from the admin access-lock. `read_session` also slides
  the TTL on every authenticated read with no absolute ceiling, so a stolen token stays valid
  indefinitely while it is exercised — and the victim re-authenticating does not evict it, giving
  them neither a signal nor a self-service remedy. *AC:* PIN-auth invalidates the user's existing
  sessions (channel-filtered) before issuing a new one; `issued_at` in the session payload with an
  absolute ceiling enforced in `read_session` independent of the sliding TTL; an active-sessions
  list with user-initiated revoke. **Planned**

- **VAPT.6 — Owner-scope the redemption lookup (intra-tenant BOLA)** · **Medium** —
  `GET /api/v1/redemption/{redemption_id}` resolves via `get_redemption(session, id, tenant_id)`,
  filtering on tenant only; object-level ownership is never checked, so any authenticated user can
  read another user's redemption in the same tenant given its id. Demonstrably an oversight rather
  than a decision: the equivalent airtime endpoint filters on `tenant_id` **and** `user_id` and its
  docstring cites "S7 A2, intra-tenant BOLA". Not enumerable (UUIDv4), so the realistic vectors are
  ids leaking via support, logs or screenshots. *AC:* `user_id` added to the filter and threaded
  through the route, matching the airtime signature; 404 not 403 on a cross-user read; the
  cross-user test airtime already has, added for redemption. **Planned**

- **VAPT.7 — Scope idempotency keys to the principal and bind them to the payload** · **Medium** —
  uniqueness is `(tenant_id, idempotency_key)` with a fully client-supplied key and no stored
  request fingerprint. Two effects: a key reused by another caller in the same tenant returns
  *their* transaction, and `P2PResponse` then discloses that transaction's id, reference, amount,
  fee and timestamp to the wrong party while the intended payment silently does not execute; and a
  client reusing a key for a genuinely different payment gets a silent no-op success that
  reconciles as completed. Mobile uses UUIDv4, but partners key on their own order ids
  (`order-1024`) and share one tenant-wide namespace. *AC:* constraint becomes
  `(tenant_id, principal_key, idempotency_key)`; a SHA-256 of the canonical body stored and
  compared on replay — identical returns the original, different returns 409
  `idempotency_key_reuse`. The server must not be safe only when clients behave. **Planned**

- **VAPT.8 — Stop conflating every `IntegrityError` with a duplicate key** · **Medium** — the
  commit handler in `ledger/service.py` treats any `IntegrityError` as an idempotency race and,
  finding no existing row, raises `DuplicateIdempotencyKey`. `ledger_entries` also carries
  `CHECK (amount > 0)` and several FKs, so a genuine data-integrity violation is reported to the
  client — and to whoever reads the logs — as a benign retry condition, with the original exception
  never logged (VAPT.10). *AC:* branch on `exc.orig.sqlstate`; only `23505` on the idempotency
  index takes the recovery path; everything else is logged with full context and re-raised
  distinctly. **Planned**

- **VAPT.9 — Rate limiting, body caps, and lockout that can't be weaponised** · **Medium** —
  `auth/rate_limit.py` limits only OTP sends per phone and 60 req/min per API key. There is no
  limiter on session-authenticated endpoints, no global limiter, and `main.py` registers **no
  middleware at all** — no trusted-host, no request-size cap, no timeout. `require_api_key` awaits
  the full body before any size check and charges quota only after the key authenticates, leaving
  failed-auth probes unthrottled. Lockout is keyed solely on `user_id` with no IP dimension, so an
  attacker who can enumerate user ids can lock every account in a tenant with five requests each —
  denial of service *through* the security control. *AC:* per-session/per-IP limiter on all
  money-mutating routes; request size capped at the ASGI layer before `await request.body()`; an IP
  dimension on failed-attempt tracking with progressive delay preferred over hard lockout; a small
  quota charged to failed API-key attempts keyed on source IP. **Planned**

- **VAPT.10 — Log declined transactions** · **Medium** — limit breaches, insufficient funds, float
  exhaustion and fail-closed config rejections all raise before any ledger write; the handler at
  `main.py:93` renders the error envelope and does not log, no middleware logs requests, and only
  `auth_attempts` persists anything (PIN/OTP only). There is no detection surface for the probing
  that precedes most wallet fraud, and VAPT.4 / VAPT.7 / VAPT.9 would leave no forensic trace if
  exploited. Compliance exposure as much as security: NFR-0160 audit expectations are met for
  approvals and silent for denials. *AC:* every `AppHTTPException` logged with structured fields
  (`error_code`, `user_id`, `tenant_id`, `transaction_type`, masked amount, IP) per the existing
  structlog conventions; a `declined_transactions` row persisted on money paths; a "Declined
  attempts" admin view over it. **Planned**

- **VAPT.11 — Reject non-positive entry amounts in `_assert_balanced`** · **Low** — the guard
  checks `credits == debits` and `credits != 0` but never that individual amounts are positive, so
  a uniformly negative entry set satisfies both. The DB `CHECK (amount > 0)` catches it at commit,
  so **no money bug is reachable today** — but the rejection then routes through VAPT.8 and
  surfaces as a spurious duplicate-key 409. *AC:* explicit positive-amount assertion in
  `_assert_balanced`, so the guard is where its own docstring already claims it is. **Planned**

- **VAPT.12 — Make the Redis quota / counter operations atomic** · **Low** —
  `consume_otp_send_quota` does `exists` → `set` and `register_failure` does `incr` → `expire` as
  separate round-trips, so concurrent requests can both pass the short-window gate or leave a
  failure counter with no TTL. *AC:* single-operation semantics via `SET NX EX` or a Lua script.
  **Planned**

- **VAPT.13 — Ship a compliant `SESSION_TTL_SECONDS` in the template** · **Low** —
  `.env.example` ships 3600s against NFR-0180's ≤15-minute mobile requirement. The comment explains
  it as dev convenience, but it is the value that gets copied. *AC:* the template carries the
  compliant value and developers raise it locally. **Planned**

**Not covered by this sweep** (open for a later pass): Celery task security, reconciliation and
segments, the rules evaluator as an attack surface, admin-UI server actions, SQL-injection review
of the analytics aggregates, and dependency CVE scanning. Mobile was excluded by instruction —
VAPT.5 and VAPT.7 have client-side counterparts worth reviewing when that exclusion lifts.

**Suggested order:** VAPT.2 (one-line default, closes an unauthenticated chain today) → VAPT.3
(small, but coordinate the Keycloak mapper or it locks out every admin) → VAPT.1 (largest; design
the claim shape first) → VAPT.4 (ship with the reconciliation query) → VAPT.5, VAPT.7, VAPT.6, then
the rest.

---

## Conflicts, numbering & provenance

Reconciled findings from consolidating the sources. Where a source disagreed with the as-built
code, **code truth wins**.

1. **Epic-18 number collision (resolved).** `docs/LINEAR_BACKLOG.md` Epic 18 = "N-Eyes Approval for Treasury & Admin Money Movements"; the threat model `docs/security/threat-models/epic-18-external-treasury.md` Epic 18 = "External Partner Treasury (Fund/Withdraw)". These are **two different features** that shared the number. **Resolution:** backlog Epic 18 keeps the number (N-Eyes); the treasury feature is relabelled **Epic 18S — External Partner Treasury** throughout this document. The original collision is noted here for traceability.

2. **`LINEAR_BACKLOG.md` summary is stale (headline).** Its "~27% delivered, 25 of 93 stories" claim and its per-epic Backlog/In-Progress labels predate most of the work. In reality Epics 10, 12–17, 18, 18S, 19–24, the analytics dashboard, and the mode-aware rewards initiative have all shipped. Statuses in this document are reconciled to the as-built code + memory, not to that summary. (See *Delivery snapshot*.)

3. **Epic 10 "Backlog" vs shipped.** The backlog marked the five remaining rule types Backlog; all **seven rule types are shipped**. Only the evaluator-to-transactions pipeline wiring is residual (composite counts + referral nth_transaction), partly closed by Epic B.

4. **Epic 6 stories mislabeled.** PIN/OTP (6.2), Roles (6.3), and HMAC (6.5) were Backlog in the file but are shipped (mobile auth, step-up PIN, the roles module, airtime + external-API HMAC).

5. **Epic 5.5 scheduled sweep.** Labelled "manual only" in the backlog, but a Celery beat now exists (rewards recon sweep, 60s, worker/beat/Flower in compose). A dedicated redemption-sweep beat may still be unbuilt — hence Epic 5 is Partial, not Shipped.

6. **`LINEAR_BACKLOG.csv` is a stale mirror.** It uses `phase-A…` labels with no epic numbers and predates the `.md`. Treat the `.md` as authoritative; the CSV is a stale import artifact.

7. **Linear tracker diverges from the docs.** Only 17 of ~34 user-types stories reached Linear before the workspace hit its issue limit mid-Epic-14; the rest were never created. Epic 14 shows 6/7 in Linear (missing the "security review" story) even though that review shipped (the threat model exists). A suspected duplicate epic set shadows the originals (archive candidate). The **docs backlog, not Linear, is the accurate record.**

8. **Epic 13 direct dialogs superseded → orphaned code.** Admin create/change-type moved to the `user_operations` maker-checker flow; the old change-type dialog + direct create/change-type actions are dead and queued for deletion. (The backend admin create-user endpoint intentionally stays for partner/seed/tests.) Related: the admin UI `rules/` route is a **shim that redirects to `/campaigns`**, slated for deletion after one release cycle (conditional on `/rules` traffic) — a transient duplicate surface, not a live epic.

9. **Epic 14 external-create audit gap.** The threat model + memory flag that partner user-creation writes **no audit-log row** — a compliance gap against "every state-changing endpoint audits" (Epic 6.6). Deferred hardening (key-idempotency, uniform-401, pre-auth body-size, key rotation) also remains open despite Epic 14 being shipped.

10. **Epic 18S funding-ceiling: doc vs decision.** The treasury threat model records the max-balance funding ceiling on partner fund as **fail-OPEN (a product decision, accepted but NOT implemented)** — a partner fund may push a wallet past its max-balance. Any requirements text asserting a hard funding cap on partner fund would contradict this decision.

11. **PRD Module 13 (Notifications) and Module 17 (Engagement Emission) are gaps.** Neither is implemented as a backend module. The reward-celebration "seen" state lives on the mobile rewards surface; the two engagement Kafka topics are declared in config but **no producer emits** to them. Epic 8 captures both as Planned.

12. **Epic 25 status confirmed.** Pricing Admin Refinements was previously marked "shipped by inference"; the as-built admin UI (grouped multi-band pricing/commission tables, the shared config-detail/compare view, inline changes-requested sections, and the config-type-filtered request list) confirms it as **Shipped**.

---

## Source map

The sources consolidated into this document.

| Source | Contributed |
|---|---|
| `docs/LINEAR_BACKLOG.md` | Master epic/story tree with AC + PRD refs — Epics 1–18, 27, 28 (richest single source; its own summary/status labels are stale). |
| `docs/LINEAR_BACKLOG.csv` | Older importable mirror using `phase-A…` labels; stale relative to the `.md`. |
| `docs/LINEAR_BACKLOG_pricing_v2.md` | Pricing-v2 initiative — Epics 19–24. |
| `docs/LINEAR_BACKLOG_user_types.csv` | User-types initiative delta — Epics 12–17 as importable rows; records Linear import state + issue-limit blocker. |
| `docs/superpowers/plans/2026-08-03-rewards-backlog-epics-stories.md` | Mode-aware rewards backlog — Epics A, B, C. |
| `docs/superpowers/plans/2026-08-03-mode-aware-rewards-and-mobile-visibility.md` + `specs/…-design.md` | Implementation plan + design behind Epics A/B/C. |
| `docs/superpowers/plans/2026-07-31-dashboard-kpi-analytics.md` + `…-design.md` | Analytics dashboard initiative (DASH). |
| `docs/superpowers/plans/2026-06-17-mobile-app.md` + `specs/2026-06-17-mobile-app-design.md` | Expo mobile app plan + design (MOB, Phases A–H). |
| `docs/superpowers/plans/2026-07-15-pricing-admin-refinements.md` + `…-design.md` | Epic 25 — Pricing Admin Refinements. |
| `docs/superpowers/specs/2026-07-12-pricing-v2-design.md` | Design behind Pricing-v2 Epics 19–24. |
| `docs/superpowers/specs/2026-07-03-user-types-design.md` | Design + locked decisions behind user-types Epics 12–17. |
| `docs/superpowers/specs/2026-07-31-channel-aware-money-controls-design.md` | Epic 26 — Channel-Aware Money Controls (new/untracked). |
| `docs/security/threat-models/epic-14-external-api.md` | Epic 14 External Partner API threat model (confirms shipped). |
| `docs/security/threat-models/epic-17-airtime.md` | Epic 17 Airtime Merchant Vertical threat model (confirms shipped). |
| `docs/security/threat-models/epic-18-external-treasury.md` | Epic 18S — External Partner Treasury threat model (the collision source). |
| `docs/security/threat-models/phase-{a,b,c,d,e1,f1..f5,g}.md` | Per-phase threat models for the foundational epics (1–7); corroborate shipped status. |
| `admin-ui/plans/001–007 + README` | Admin-UI motion/perf polish tasks (not product epics). |
| `.claude/memory/MEMORY.md` + per-project memory files | Architectural decision log — confirmed shipped statuses for rules, user-types, user-ops maker-checker, unified approvals, step-up, analytics, tenant provisioning, rewards internal wiring, and the ledger/money-path hardening items. |
| As-built code inventories (`inv-backend-core`, `inv-rewards-rules`, `inv-frontends`) | The as-built truth used to set every story's Status by code reality rather than by stale backlog labels. |
| `docs/02-prd.md` | The 17 PRD functional modules used for the Epic-index cross-reference. |
