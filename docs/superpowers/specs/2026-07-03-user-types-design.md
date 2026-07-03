# User Types — Design Spec

**Date:** 2026-07-03 · **Status:** Approved (Manan, 2026-07-03) · **Tracking:** Linear WAL project
**Related:** [Product PRD](../../02-prd.md) Modules 1/5/6, [Data architecture](../../06-data-architecture.md), [UI layouts §5.2/5.6](../../04-ui-layouts.md)

## 1. Context

The platform currently has no concept of a business user type. All users are implicitly consumers; merchants exist only as a stubbed `accounts.merchant_id` column, and Segments (marketing cohorts) and Roles (transaction permissions) cover adjacent but different needs. This spec introduces **five user types** — `consumer`, `agent`, `super_agent`, `merchant`, `head_merchant` — as a first-class dimension on users, drives **pricing and limits configuration by user type**, adds **admin UI for creating users and changing their type**, exposes an **externally callable user-creation API** (OpenAPI-documented), and delivers the **first merchant vertical: airtime merchants** (collection into a merchant ledger account, then external provisioning).

The PRD v1.3 does not define these types; a PRD update (Module 1 + glossary + cross-refs in Modules 5/6) ships with epic E1 since PRDs are this repo's source of truth.

## 2. Locked decisions

| # | Decision | Choice |
|---|---|---|
| D1 | Merchant modeling | Merchants are **users** with `user_type=merchant` plus a `merchant_profiles` extension table. No separate merchants entity; `accounts.merchant_id` stub remains unused (deprecate later). |
| D2 | Email-only users | **Record-only** in v1: they exist, hold accounts, appear in admin, but cannot authenticate until a verified phone identifier + PIN are added. No email OTP in v1. |
| D3 | External API auth | **Per-tenant API keys + HMAC request signing** using the existing `X-Sasai-Signature` helper (`backend/app/auth/hmac.py`, 300 s replay window). Not Keycloak client-credentials. |
| D4 | Hierarchy | Store `parent_user_id` now with type-compatibility validation; **all commission/roll-up logic deferred** to a later epic. |

## 3. Data model

### 3.1 `users` (extend)

- `user_type` — PG enum `user_type` (`consumer`, `agent`, `super_agent`, `merchant`, `head_merchant`), `NOT NULL DEFAULT 'consumer'`. Migration backfills existing rows to `consumer`. Index on `(tenant_id, user_type)`.
- `parent_user_id` — nullable UUID self-FK. Compatibility enforced in the service layer (cross-row rules don't fit a CHECK): `agent` → parent must be a `super_agent`; `merchant` → parent must be a `head_merchant`; both optional. `consumer`, `super_agent`, `head_merchant` must have NULL parent. Parent must belong to the same tenant.

### 3.2 `merchant_profiles` (new)

One-to-one with users of type `merchant`/`head_merchant`: `user_id` (PK, FK users), `tenant_id`, `business_name`, `category`, `provider_config` JSONB (e.g. airtime provider routing), settlement fields, timestamps. Created transactionally with the user (or on type change into a merchant type).

### 3.3 Merchant collection account

New account type constant `merchant_collection` in `backend/app/shared/models/accounts.py`. One account per `(tenant, merchant user, merchant_collection, currency)` via the existing partial unique index; provisioned when a merchant profile is created (per configured currency). Reuses `accounts.user_id` ownership per D1.

### 3.4 Pricing and limits configs (extend all three)

Add nullable `user_type` (same enum) to `pricing_configs`, `limit_configs`, `wallet_limit_configs`. `NULL` means "default — applies to all types". Uniqueness must treat NULL as a real value: extend the unique constraints with `user_type` using `UNIQUE ... NULLS NOT DISTINCT` (PG ≥ 15) or paired partial unique indexes if the local PG is older — decide in the migration story.

**Resolution precedence (applies to fee quoting and limit enforcement):** exact match on existing dimensions + caller's `user_type` first; else the `user_type IS NULL` default row. One query: `ORDER BY user_type NULLS LAST LIMIT 1`. No per-user overrides in v1.

## 4. API surface

### 4.1 Admin (Keycloak `platform-admin`, existing stack)

- `POST /api/v1/users` (extend): accepts `user_type` (default `consumer`), `parent_user_id`, profile; identifiers may be **email or phone or both — at least one required**. Idempotency-Key honored. Creating a merchant type requires the merchant-profile payload. Audit-logged (existing pattern).
- `PATCH /api/v1/users/{user_id}/type` (new): body `{new_type, parent_user_id?, reason}`. Reason mandatory (audit). Validations: parent compatibility (§3.1); leaving a merchant type is **blocked while any `merchant_collection` account has non-zero balance** (`USER_TYPE_TRANSITION_BLOCKED`); entering a merchant type requires profile payload. Idempotency-Key honored; emits `user.type_changed` after commit.

### 4.2 External partner API (new, per D3)

- `api_keys` table: `tenant_id`, `key_id`, `secret_hash` (never stored in plaintext, shown once on creation), `status`, `created_at`, `last_used_at`. Managed from the Tenants admin screen (API keys tab already exists in the layout spec).
- `POST /api/v1/external/users`: same semantics as admin create. Auth = `X-Sasai-Api-Key` + `X-Sasai-Signature` (HMAC-SHA256, `t=<unix>,v1=<hex>`, 300 s replay window). Tenant derived from the key — **never from the payload**. Idempotency-Key required. Per-key rate limiting (Redis).
- OpenAPI: `external` tag with curated request/response examples and the standard `{error_code, message}` envelope; spec export checked into `docs/` for partner distribution.

### 4.3 Error codes (new)

`IDENTIFIER_REQUIRED`, `USER_TYPE_INVALID_PARENT`, `USER_TYPE_TRANSITION_BLOCKED`, `MERCHANT_PROFILE_REQUIRED`, `API_KEY_INVALID`, `SIGNATURE_INVALID`, `SIGNATURE_REPLAYED`, `RATE_LIMITED` — all via the existing `AppHTTPException` envelope.

## 5. Admin UI (patterns from the limits pages)

- **Users page:** enable the disabled "Register user" button → create-user dialog (identifier type toggle email/phone, profile fields, user-type selector, parent picker shown for agent/merchant, merchant-profile fields shown for merchant types). Server action returning `{ok} | {ok:false, errorCode, message}` + `revalidatePath`.
- **User detail card:** user-type badge; **Change type** action with confirm modal requiring a reason; hidden below `platform-admin`. Parent shown/linked when set.
- **Limits & Pricing pages:** user-type column ("All types" for NULL) + user-type selector in the create dialogs.

## 6. Airtime merchant flow (E6)

1. **Purchase:** consumer buys airtime from a merchant → one transaction, double-entry: debit consumer `financial_wallet`, credit merchant `merchant_collection` (+ fee legs to `system_fee_collected` per type-aware pricing). `AirtimeRecharge` row created `PENDING`, linked to the transaction. Limits enforced with the consumer's user type.
2. **Provisioning:** after DB commit (NFR-0130), a Celery task calls the external airtime provider (adapter interface; provider config from `merchant_profiles.provider_config`). Success → recharge `COMPLETED`, event emitted. Failure after bounded retries with backoff → **reversal transaction** (new ledger entries: merchant_collection → consumer wallet; ledger stays append-only) and recharge `FAILED`/`REVERSED`.
3. **Reconciliation:** stuck `PENDING` recharges surface in the existing reconciliation queue.

## 7. Events & audit

- New Kafka topic `wallet.users.lifecycle` (add to `config.Topics` + `sasai-wallet-infra/kafka/topics.sh`): `user.created`, `user.type_changed`. Partition key `user_id`; emitted post-commit; consumers idempotent via `event_ingestion_log`.
- Airtime provisioning outcomes ride `wallet.transactions.completed` (+ recharge status in payload).
- Every admin/external mutation writes an audit-log entry (who, before/after type, reason). Identifiers masked per compliance rules; PIN/OTP/API secrets never logged (NFR-0170).

## 8. Testing (automation-testing agent owns)

- API tests per new/changed endpoint: happy path, validation failures, **tenant isolation**, **idempotency replay**, RBAC (admin role, API key auth negative cases incl. bad/replayed signatures).
- Precedence matrix tests for pricing and limits (typed row vs NULL default vs no config).
- Ledger invariant tests for the airtime flow: entries balance per transaction, no UPDATEs on ledger, reversal correctness, balance = SUM(entries).
- Migration tests: backfill to `consumer`, enum + constraint integrity.
- Kafka: lifecycle events emitted post-commit; consumer idempotency.

Security agent reviews E1–E3 before merge (auth + money + PII surfaces). Frontend automation tests deferred per coding guidelines.

## 9. Epic / story map (Linear, WAL project)

- **E1 — User type foundation:** enum + `parent_user_id` migration & backfill; identity schemas expose type; `PATCH /users/{id}/type` (+audit, +event, +idempotency); `wallet.users.lifecycle` topic; PRD update; tests.
- **E2 — Admin create user & change type (UI+API):** create-user endpoint hardening (email-or-phone, type, merchant profile); create-user dialog; change-type action; type badge; tests.
- **E3 — External user-creation API:** `api_keys` model + tenant admin management; HMAC auth dependency + rate limiting; `POST /external/users`; curated OpenAPI + exported spec; tests; security review.
- **E4 — Type-aware limits:** migration (both config tables); resolution precedence in enforcement; CRUD schemas; limits UI; precedence tests.
- **E5 — Type-aware pricing:** migration; `quote_fee` precedence; CRUD schemas; pricing UI; precedence tests.
- **E6 — Airtime merchant vertical:** `merchant_profiles` + collection account provisioning; purchase flow (ledger); provisioning adapter + Celery task + reversal path; reconciliation hook; events; tests.

Dependency order: E1 → (E2, E3, E4, E5 in parallel) → E6 (needs E1 + E4 + E5).

## 10. Out of scope (v1)

Commission calculation and hierarchy roll-ups; email OTP authentication; per-user (non-type) pricing/limit overrides; merchant self-onboarding portal; dynamic segments; USSD flows; migration of `accounts.merchant_id` (left dormant).
