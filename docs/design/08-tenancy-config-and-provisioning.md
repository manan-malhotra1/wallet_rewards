# 08 — Tenancy, Config & Provisioning

> **Document type:** Low-Level Design (LLD) — the *how*.
> **Purpose:** how a tenant is created and made money-ready — tenant CRUD + `business_type`,
> auto-provisioning of instruments/services/system accounts, the instrument & service catalogs and
> per-service access policy, per-tenant admin branding, and the external partner API (API keys +
> HMAC + the partner-facing money endpoints).
> **Related:** code in `backend/app/modules/{tenants,instruments,services,api_keys,external}/`,
> `backend/app/auth/{api_key,hmac,rate_limit}.py`, `admin-ui/lib/brand-palette.ts`.
> **PRD:** Module 14 (Tenant & Platform Config, Pay-PRD 0860–0909).
> **Read first:** [README (HLD)](README.md) §3 (deployment modes) & §8,
> [02 — Ledger](02-ledger-accounts-and-money-movement.md) (account types),
> [06 — Events Ingestion](06-events-ingestion-and-mode-awareness.md) (external event sources).

---

## 1. Tenants — `modules/tenants/`

A tenant is the isolation boundary: `tenant_id` is on every domain table and resolved from the auth
principal, never the request body. Endpoints under `/api/v1/tenants` (admin): `GET` list, `POST`
create (201), `GET /{id}`, `PATCH /{id}`, plus `GET`/`PUT /{id}/branding` (§5).

- **`business_type`** (`wallet` / `rewards` / `both`) is the master switch resolved in
  `shared/tenant_mode.py` — it decides whether wallet money paths are live and whether rewards are
  driven from internal wallet activity or external Kafka (full matrix in [README §3](README.md)).
- **`base_currency`** is the tenant's own settlement currency and is **load-bearing at provisioning
  time** — the tenant's baseline instrument is minted in *its* currency, not a hardcoded ZAR.
- CRUD: `create_tenant` (§2), `update_tenant`, `get_tenant_by_id`.
- **Exceptions:** `TenantNotFound` (404), `TenantNameAlreadyExists` (409).

---

## 2. Auto-provisioning on tenant creation — `provision_tenant_defaults`

The gap this closes: a tenant created without instruments/services/system accounts is *empty* — no
money can move through it. So **`create_tenant` calls `provision_tenant_defaults(session, tenant)`
in the same flow**, and creation-path tests assert the tenant is fully money-ready afterward.

`provision_tenant_defaults` provisions, in the **tenant's own `base_currency`**:

1. **Baseline currency instrument** — one financial instrument in `tenant.base_currency` (e.g. `USD`),
   with a currency-appropriate symbol.
2. **The `PTS` points instrument** — always, regardless of `base_currency`, since rewards are
   points-denominated.
3. **Baseline services** — the default `transaction_type` catalog (P2P, cash-in/out, airtime, …).
4. **System accounts** — the operator-side accounts each money path needs (fee/tax/commission
   collection, cash float, etc.), created per instrument.

Instrument provisioning itself (creating a *new* currency later) reuses the same account machinery:
`instruments.create_instrument` → `_provision_system_accounts` (system accounts for the new
currency) → `_backfill_user_accounts` (a wallet of the new currency for every existing user, so
adding a currency doesn't leave live users without an account).

---

## 3. Instruments catalog — `modules/instruments/`

The catalog of value units: currencies (`financial_wallet`) and points (`points_account`).
Endpoints under `/api/v1/instruments` (admin): `GET` list, `POST` create (201), `PATCH /{id}`,
`DELETE /{id}` (soft-delete).

- `create_instrument(...)` — mints the instrument, then `_provision_system_accounts` +
  (optionally) `_backfill_user_accounts` so existing users receive a wallet of the new unit.
- `update_instrument`, `soft_delete_instrument`, `list_instruments`, `get_instrument_by_id`.
- **Exceptions:** `InstrumentNotFound` (404), `InstrumentCodeAlreadyExists` (409).

The admin `/instruments` page adds currencies (up to 10-char codes) with an optional backfill toggle;
ZAR/PTS are seeded by provisioning.

---

## 4. Services catalog & access policy — `modules/services/`

Defines each `transaction_type` (service) and its two access lists. Endpoints under
`/api/v1/services` (admin): `GET` list, `POST` (201), `PATCH /{id}`, `DELETE /{id}` (soft-delete).

**Base vs derived services (2026-08-18).** Every catalog row declares a `kind`:

- **`base`** — a flow the platform actually implements; its code is in
  `app/shared/services_registry.py::BASE_SERVICE_CODES`. Provisioned per tenant by
  `provision_tenant_defaults`, **never creatable through the admin API** (a base row with no
  implementation is dead config). A tenant may still enable/disable it and set its access policy.
- **`derived`** — operator-created. `POST /api/v1/services` creates *only* these, and
  `base_service_code` is required: the row executes its base's flow unchanged while carrying its
  own pricing, limits, channels and permitted initiators. One level only; base rows are
  undeletable (`409 base_service_protected`) and `base_service_code` is immutable.

At request time `resolve_service_code(...)` turns an optional `service_code` into the code that
drives permission, pricing, limits and the recorded `transaction_type`; omitting it reproduces
pre-existing behaviour exactly. `transactions.base_transaction_type` is denormalised so clients
group by flow without knowing every derived code. Pricing and limits are **never inherited** — a
derived service fails closed (422) until both are configured. Access policy is **narrowing-only**,
enforced at save time and re-intersected at resolution, so narrowing a base tightens its derived
services automatically. Reward rules target the **resolved** code (a rule on the base does not fire
for a derived service), while reward *eligibility* and step-up PIN both key off the **base**.

Spec: `docs/superpowers/specs/2026-08-17-service-variants-design.md`.

The access policy is enforced on **every money path** by `assert_service_allowed(session, service,
user, channel)` (doc 03, step 3):

| Field | Axis | Violation |
|---|---|---|
| `allowed_user_types` | **WHO** may call the service | `ServiceNotAllowedForUserType` (403) |
| `allowed_channels` | **HOW** — mobile / web / partner-api / agent | `ServiceNotAllowedOnChannel` (403) |

An unset list = unrestricted on that axis. `create_service`, `update_service`, `soft_delete_service`,
`list_services`, `get_service_by_id`. The catalog is the source of truth for the Limits / Pricing /
Campaigns dropdowns in the admin UI. **Exceptions:** `ServiceNotFound` (404),
`ServiceCodeAlreadyExists` (409), plus the two policy 403s.

---

## 5. Per-tenant admin branding

Cosmetic theming is per-tenant and applied per active tenant, with **no maker-checker** (it moves no
money and rewrites no config). Backend: `GET`/`PUT /api/v1/tenants/{id}/branding`
(`get_tenant_branding` / `update_tenant_branding`) persist two brand colours + an optional icon on
`TenantConfig`. The palette derivation is a **pure TS engine**, `admin-ui/lib/brand-palette.ts`:

- **`deriveTokens(accent, light)`** produces the full shadcn dark + light token set from just two
  inputs (a deep `accent` + a pale `light`), working in **OKLab perceptual space** so intermediate
  stops stay perceptually even.
- **`ramp()`** interpolates accent → light across **7 golden-ratio stops** (`GOLDEN_STOPS`).
- **`darken()`** scales the accent toward black for calm dark surfaces — deliberately **not** `t < 0`
  extrapolation, which would go electric.
- `--destructive` is intentionally excluded so status colours stay constant across tenants.

Tokens are emitted **server-side** by `components/branding/tenant-theme-style.tsx` as an inline
`<style>` overriding the shadcn CSS vars for `:root` + `.dark` (no FOUC). Switching tenant
re-derives and re-themes the whole app. UI detail: [doc 09](09-admin-ui.md).

---

## 6. External partner API — `modules/external/` + `auth/api_key.py`

The partner-facing money surface. Unlike the admin/user surfaces it authenticates with an **API key**
(`require_api_key` → `ApiKeyPrincipal`), and the **tenant is always derived from the key**, never the
body.

### 6.1 API-key lifecycle — `modules/api_keys/`

`/api/v1/api-keys` (admin): `POST` mint (201, secret returned **once**), `GET` list, `POST
/{key_pk}/revoke`. `create_api_key` (`_generate_credentials` → key-id + secret) can bind the key to a
`merchant_user_id` (`_assert_merchant_user`) for the merchant-cashin flow. Every action is audit-logged.

### 6.2 `require_api_key` — auth + HMAC + rate limit

Three checks, in order (`auth/api_key.py`):

1. **Key resolution** — unknown or revoked key → `ApiKeyInvalid` (401), *no* existence leak
   (NFR-0220 — a wrong key and a revoked key are indistinguishable to the caller).
2. **HMAC signature** — `X-Sasai-Signature` over the **raw request body** is verified via
   `auth.hmac.verify_signature` (shared with provider callbacks): checks presence, format, timestamp
   skew, and the signature itself (`signature_missing` / `_malformed` / `_timestamp_skew` /
   `invalid_signature`, all 401).
3. **Per-key rate limit** — `auth.rate_limit.consume_api_key_quota` → `RateLimited` (429).

### 6.3 Partner money endpoints — `/api/v1/external` (all `[IDEM]`)

| Endpoint | Service fn | Move |
|---|---|---|
| `POST /users` | `external_create_user` | create a user in the key's tenant |
| `POST /fund` | `external_fund` | fund a user wallet from the operator float |
| `POST /withdraw` | `external_withdraw` | withdraw from a user wallet |
| `POST /merchant-cashin` | `merchant_cashin` | merchant funds a consumer from the merchant's own wallet (**merchant-bound key only**) |

All route through `post_transaction` (doc 02), so the balance guard, cash-float floor, and
idempotency all apply unchanged. **Leak prevention:** on the partner surface `external_fund` catches
the guard's **`InsufficientFloat`** and re-raises it as **`FundingTemporarilyUnavailable`** (503) — a
partner is never told the operator's float is empty; it sees a transient-unavailable signal.
**Exceptions:** `ApiKeyInvalid` (401), `ApiKeyNotFound` (404), `NotAMerchantKey` (403),
`MerchantUserRequired` (422), `FundingTemporarilyUnavailable` (503).

---

## 7. External event-source registration

Distinct from API keys: a `rewards`-mode tenant registers **event sources** (with a shared secret for
HMAC proof-of-origin) so partner engagement events can drive rewards. That pipeline —
registration, HMAC verification, dedup, normalisation, and `business_type` gating — is documented in
[06 — Events Ingestion & Mode Awareness](06-events-ingestion-and-mode-awareness.md). The admin
`/events` page registers sources via `POST /api/v1/events/sources`.

---

## 8. Requirement map

| Requirement | Built as |
|---|---|
| Pay-PRD 0860–0900 (tenant & platform config) | `tenants` CRUD + `business_type`; `instruments` / `services` catalogs |
| Tenant is money-ready on create | `create_tenant` → `provision_tenant_defaults` (own base_currency instruments + services + system accounts) |
| Add a currency later | `instruments.create_instrument` → `_provision_system_accounts` + `_backfill_user_accounts` |
| Per-service WHO/HOW access | `services.assert_service_allowed` (`allowed_user_types` / `allowed_channels`) |
| Per-tenant branding | `tenant/{id}/branding` + `admin-ui/lib/brand-palette.ts` (OKLab, golden-ratio ramp) |
| Pay-PRD 0901–0909 (partner API) | `external` endpoints, `require_api_key` (HMAC + rate limit), tenant-from-key, `InsufficientFloat` → 503 mask |
| Partner credential mgmt (Epic 14) | `api_keys` mint-once / list / revoke |

The read-only per-currency **analytics dashboard** (money never summed across currencies; revenue =
operator fee only) is documented in
[11 — Cross-cutting: Observability, Compliance, Security](11-cross-cutting-observability-compliance-security.md).
