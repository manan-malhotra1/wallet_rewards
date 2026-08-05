# 09 — Admin UI (Next.js 16)

> **Document type:** Design (HOW). The admin operator console — how the Next.js App Router app is
> structured, how it talks to the backend, and how each surface is built.
> **Related:** [`.claude/rules/frontend-admin.md`](../../.claude/rules/frontend-admin.md) (conventions),
> [`docs/03-ux-philosophy.md`](../03-ux-philosophy.md) + [`docs/04-ui-layouts.md`](../04-ui-layouts.md) (the
> design system — colour tokens, layout grammar, component grammar; **not duplicated here**),
> [04-maker-checker-and-approvals](04-maker-checker-and-approvals.md) (the backend the config/money/user
> surfaces drive), [11-cross-cutting](11-cross-cutting-observability-compliance-security.md) (audit, analytics).
> **README:** see the [design index](README.md) §9.
> **Audience:** an engineer working on `admin-ui/`.

---

## 1. Architecture at a glance

**Stack:** Next.js 16.2.6 (App Router, React 19) · next-auth v5 beta (Keycloak) · Tailwind CSS v4 ·
shadcn/ui over Radix primitives · `cmdk` (command palette) · `next-themes` (dark default) · Recharts ·
`zod`. Tests: **Vitest + Testing Library (jsdom)**.

The app is **server-component-first**. The data-flow contract has exactly three tiers:

1. **Server components** (route `page.tsx`) call the typed API client in
   [`admin-ui/lib/api-endpoints.ts`](../../admin-ui/lib/api-endpoints.ts) *directly*. The Keycloak Bearer
   token is read server-side from the next-auth session, so it never reaches the browser.
2. **Client components** (`'use client'`) hold state / interactivity but **never fetch the backend**. They
   call `"use server"` actions co-located in each route's `_actions.ts`.
3. **Server actions** (`_actions.ts`) re-enter the typed client, then `revalidatePath` / `redirect`.

Every page is `export const dynamic = "force-dynamic"` — the console shows live operator data, never a static
cache. `lib/api.ts` is the server-only fetch primitive (typed `ApiError`, `{error_code, message}` envelope);
`lib/api-endpoints.ts` wraps every backend route 1:1; `lib/api-types.ts` mirrors the backend Pydantic
schemas + domain enums.

> **Accuracy flag — TanStack Table.** `@tanstack/react-table` v8 is declared in `package.json` and named in
> `frontend-admin.md`, but there are **zero imports**. All tables are hand-rolled on the shadcn
> `components/ui/table.tsx` primitive. Treat the "TanStack Table" convention as aspirational, not as-built.

---

## 2. Authentication & the edge gate

Auth is next-auth v5 with a **Credentials provider** doing Keycloak **Direct Access Grants** — the login form
lives inside the admin UI (no redirect to Keycloak's hosted page). Config:
[`admin-ui/auth.ts`](../../admin-ui/auth.ts).

| Concern | Implementation |
|---|---|
| Sign-in | `authorize()` POSTs `username`+`password` to `/realms/{realm}/protocol/openid-connect/token` (grant_type=password). |
| Session claims | `decodeJwtPayload()` pulls `sub` / `preferred_username` / `email` / `realm_access.roles` onto the JWT + session (no signature check — the token was just minted; the backend re-verifies). |
| Refresh | `refreshAccessToken()` runs in the `jwt` callback with a 30s expiry safety window; failure marks `error: "refresh_failed"`. |
| Edge gate | [`admin-ui/middleware.ts`](../../admin-ui/middleware.ts) — public `/login` + `/api/auth`; everything else redirects to `/login?from=…`. `auth.ts` is Edge-compatible (uses `atob`/`TextDecoder`, not `Buffer`). |
| Login flow | `app/login/page.tsx` + `login-form.tsx` (React 19 `useActionState`) + `actions.ts` (`loginAction` → `signIn("credentials")`, `safeRedirect` open-redirect guard). Root `app/page.tsx` → `/dashboard`. |

**Trust boundary:** the front-end JWT decode is for *display metadata only*. The **backend independently
re-validates every JWT against Keycloak JWKS** on every API call, and role checks in components are
convenience affordances only — the backend is the authority. Direct-grant deliberately bypasses Keycloak
MFA/consent (accepted for a VPN-gated operator app; see the `auth.ts` docstring).

---

## 3. The app shell

Composed in [`components/app-shell/app-shell.tsx`](../../admin-ui/components/app-shell/app-shell.tsx) as
`Sidebar + Topbar + <main> + CommandPalette`. The authenticated layout
([`app/(authenticated)/layout.tsx`](../../admin-ui/app/(authenticated)/layout.tsx)) is the composition root:
it guards the session (`auth()` → redirect `/login`), fetches `listTenants()`, resolves the active tenant,
emits `<TenantThemeStyle>` (per-tenant palette, §6), and computes the **Approvals badge** by summing PENDING
config + money + user operations gated on the operator's approver roles. On an unreachable backend it renders
`<ServiceUnavailable variant="maintenance">` instead of crashing.

| Shell part | File | What it does |
|---|---|---|
| Sidebar | `app-shell/sidebar.tsx` | 240px, tenant logo or `SasaiLogo`; three nav groups (below). |
| Topbar | `app-shell/topbar.tsx` | tenant switcher, ⌘K trigger, notifications bell, theme toggle, user menu. |
| Tenant switcher | `app-shell/tenant-switcher.tsx` | Radix popover combobox → `setActiveTenantAction` + `router.refresh()`. |
| Command palette | `command-palette/command-palette.tsx` | single `cmdk` dialog on ⌘K. |

**Nav groups:** OPERATIONS (Dashboard, Users, Merchants, System wallets, Reconciliation[badge]) ·
CONFIGURATION (Campaigns, Segments, Budgets, Limits, Step-up PIN, Pricing → Service charges / Commission /
Taxes, Approvals[badge], Redemption, Services, Instruments, Tenants, API keys) · AUDIT (Audit log, Events).

**Command palette** has two groups — **Navigate** (17 "Go to…" routes) + **Switch tenant** — plus a Vim-style
`g`-then-key sequence (`g d`→dashboard, `g u`→users, `g r`→campaigns, `g a`→audit, `g m`→merchants,
`g c`→reconciliation, `g p`→redemption, `g t`→tenants, `g e`→events).

---

## 4. Per-page design

Every route folder follows the same shape: `page.tsx` (server component, initial fetch) + `_actions.ts`
(server actions) + `_components/` (client components). The interesting patterns:

### Dashboard / analytics — `/dashboard`
Server component reads `range`/`granularity` from the URL, does an initial fetch, and hands off to
`DashboardClient` with `key={activeTenantId}` (forces remount on tenant switch so state never bleeds across
tenants). Controls: `TimeRangeSwitcher`, `CurrencyToggle` (multi-select chips, ≥1 kept, hidden for
single-currency tenants). **Money is never summed across currencies:** `MoneyStatTile` renders one line per
currency; non-money KPIs use `StatTile`. Charts are props-fed (no own fetch): revenue, net-flow (one card per
currency), service-mix, rewards, users-growth, user-type, status-breakdown, trend. `loadDashboardData` fans
out `Promise.allSettled` over ~12 `GET /api/v1/analytics/*` endpoints (revenue = **fee only**). See
[11-cross-cutting](11-cross-cutting-observability-compliance-security.md) §analytics.

### Users — `/users`
Identifier lookup → user detail. `UserLookupForm` resolves phone/email/account/card → `user_id`; server fetches
detail + transactions and detects any open `update_user` request to block duplicate edits. `UserDetailCard`
(navy hero, KPI band, collapsible Personal/KYC/Address/Docs/Accounts/Transactions sections; `WalletBalances`
per-currency snap-slider). **Maker-checker create/edit:** `CreateUserDialog` *proposes* a `create_user` op;
`EditUserDrawer` *proposes* an `update_user` op with only changed fields (identifiers read-only), blocked when
an open op exists — **approver role = user-approver**. Immediate `platform-admin` affordances:
`AccessLockControl` (login-lock / txn-lock / restore), `ResetPinButton`, `UnlockButton` (release PIN lockout),
`AddIdentifierDialog` (never card), `VerifyIdentifierButton` (manual account-number verify).

### Unified approvals — `/approvals`
One screen, **role-gated tab bar** over three backend queues: **Configuration** (config-approver) ·
**Transactions** (treasury-approver) · **Users** (user-approver). Platform-admin sees all tabs; others only
tabs matching an approver role. The server fetches each visible queue's **full dataset (all statuses —
tab counts need every row)**. `ApprovalsToolbar` applies four client-side facets over already-loaded rows
(free-text search, status segmented control with counts, type multi-select, date-range preset), mirrors them
to the URL, and renders removable filter chips + "X of Y". The faceting model lives in the pure helper
[`lib/approvals-filter.ts`](../../admin-ui/lib/approvals-filter.ts) (`applyFilters` / `countByStatus` /
`summarize`; `STATUS_KEYS`, `DateRangeKey`). It delegates to the **reused per-domain tables + drawers**
(`ConfigRequestsTable` / `MoneyOperationsTable` / `UserOperationsTable`), which remain the live implementation.

> **Legacy redirect stubs.** `/user-operations`, `/money-operations`, `/config-requests` are thin
> `redirect()` pages into `/approvals?tab=…`. Their tables/drawers/actions are imported by the toolbar and are
> still the real code. The shared maker-checker lifecycle (PENDING → CHANGES_REQUESTED → APPLIED/WITHDRAWN;
> approve / request-changes[mandatory comment] / revise / resubmit / withdraw; checker ≠ maker) is described
> in [04-maker-checker-and-approvals](04-maker-checker-and-approvals.md).

### Config tables → maker-checker
`/pricing` (service charges), `/limits` (service + wallet limits), `/commissions`, `/taxes`, `/step-up` share
one pattern: a **grouped table** (bands folded into scope rows via [`lib/config-groups.ts`](../../admin-ui/lib/config-groups.ts)),
a `Create…Dialog`, and a `…ChangesRequested` panel surfacing in-flight proposals inline (maker-gated revise).
**All writes flow through the config maker-checker pipeline** (`POST /api/v1/config-requests`,
propose/revise/approve) — the direct create/delete endpoints were removed backend-side. `platform-admin`
gates `canPropose`. These surfaces make invariant #12 visible: every txn type must have a config row (a
zero-fee or unlimited limit is a real, explicit row — never an implicit default). Scope-key matching of a row
to its open request is in [`lib/config-scope.ts`](../../admin-ui/lib/config-scope.ts).

### Campaigns — `/campaigns` (the 7-rule-type wizard)
"Campaign" is the operator label for a backend **Rule** (PRD §6.9); the URL was renamed from `/rules` but the
API path stays `/api/v1/rules`. **`app/(authenticated)/rules/` is a legacy shim** — `rules/page.tsx` is a
server `redirect("/campaigns")`, scheduled for deletion after one release cycle. `CreateCampaignDialog` is a
2-step wizard: **Step 1** picks one of the 7 rule types (`milestone`, `streak`, `first_time`, `value_based`,
`composite` with `ConditionsEditor`, `campaign`/time-boxed, `referral`); **Step 2** configures type-specific
fields + reward (points/cashback + value) + stop-after-N + live summary + an **optional inline per-campaign
budget**. Submits via `createCampaignWithBudgetAction` (campaign then budget; budget failure surfaces without
undoing the campaign). `CampaignsTable` shows live performance (Fires + Unique users from `reward_events`;
per-row failure degrades to em-dashes). See [05-rewards-rules-and-referral](05-rewards-rules-and-referral.md)
for the engine.

### Treasury — `/system-wallets`
Cards per platform-owned ledger account with balances. Header actions **New bank mirror** / **Withdraw** /
**Fund user**; per-row **Adjust** / **Transactions** + rename bank mirror. Every money move **proposes a
`MoneyOperation`** (Epic 18 maker-checker) rather than executing. Bank mirrors are `operator_adjustment`
counter-legs; the cash float is `system_cash_inflow` (overdraft-floored — must be pre-funded via
adjust-system-wallet). Reads `GET /api/v1/treasury/system-wallets`; proposes via `/treasury/*`.

### Tenants & branding — `/tenants`
Identity cards (name + business_type inline-editable; id/realm/currency/status read-only). `CreateTenantDialog`
collects name + business_type + base_currency + optional branding; the **backend auto-provisions the tenant's
baseline instruments + services** in its own base_currency (see
[08-tenancy-config-and-provisioning](08-tenancy-config-and-provisioning.md)). `BrandingDialog` writes
per-tenant branding **directly** (no maker-checker) via `PUT /api/v1/tenants/{id}/branding`, with a live
palette preview, then revalidates the layout so the whole app re-themes. Branding engine → §6.

### Remaining routes (one line each)
| Route | Purpose |
|---|---|
| `/redemption` | Manual-review queue + provider registration (`shared_secret` for HMAC callbacks). |
| `/audit` | Read-only immutable audit log, before/after JSON drawer; humanized via `lib/audit-labels.ts`. |
| `/reconciliation` | Operator daily-driver: pending + manual-review queues + inline **sweep** trigger. |
| `/services` | Service catalog (source of truth for Limits/Pricing/Campaigns dropdowns) + per-service access policy. |
| `/instruments` | Currencies + points accounts; ZAR/PTS auto-seeded; add more (optional user backfill). |
| `/budgets` | Reward-issuance caps per (scope, window). |
| `/segments` | Static cohorts (dynamic = Phase 2). |
| `/api-keys` | Partner API credentials; secret revealed once, revoke disables; optional merchant bind. |
| `/events` | Register external event sources with a shared secret (no list endpoint yet). |
| `/merchants` | Module 17 placeholder (empty state so the nav entry doesn't 404). |

---

## 5. The `lib/` helper layer

[`admin-ui/lib/`](../../admin-ui/lib/) is where all non-visual logic lives (and where the coverage gate bites —
§7). Grouped by concern:

- **Backend I/O:** `api.ts` (server-only fetch, typed `ApiError`), `api-endpoints.ts` (every route wrapper),
  `api-types.ts` (TS mirrors of backend schemas), `is-backend-unreachable.ts` (network-vs-HTTP classifier).
- **Tenant / theme:** `active-tenant.ts` (`sasai_active_tenant` cookie resolution), `brand-palette.ts`
  (OKLab palette, §6), `chart-colors.ts` (Recharts series/status colours from brand vars).
- **Config & approvals:** `config-groups.ts` (fold bands into scope groups), `config-scope.ts` (row ↔ open
  request matching), `approvals-filter.ts` (unified faceting), plus the label helpers `config-type-label.ts`,
  `money-operation-label.ts`, `service-label.ts`, `transaction-type-label.ts`, `user-operation-label.ts`,
  `audit-labels.ts`.
- **Formatting:** `analytics-format.ts` (delta helpers), `utils.ts` (`cn`, formatters).

UI kit: 22 shadcn primitives under `components/ui/*` including `money.tsx` (all financial values),
`status-pill.tsx`, `kpi-card.tsx`, `metrics-strip.tsx`. Branding components under `components/branding/`
(`sasai-logo`, `tenant-theme-style`, `service-unavailable`).

---

## 6. The per-tenant branding engine

[`admin-ui/lib/brand-palette.ts`](../../admin-ui/lib/brand-palette.ts) turns a tenant's **two brand colours**
(a deep `accent` + a pale `light`) into the full shadcn dark+light design-token set. It is **pure TypeScript**
— no React, no backend, no dependencies — working entirely in the **OKLab perceptual colour space** so the
ramp reads as evenly spaced to the eye rather than bunching in the shadows.

| Function | Role |
|---|---|
| `deriveTokens(accent, light)` | Produces the complete `{ dark, light }` shadcn token map. |
| `ramp()` | Interpolates accent→light in OKLab at 7 golden-ratio stops (`GOLDEN_STOPS`). |
| `darken()` | Scales the accent toward black for calm dark surfaces — **not** `t<0` extrapolation, which would go electric. |

Defaults: accent `#243B8F`, light `#FFF0C9`. `--destructive` is deliberately excluded so status colours stay
constant across tenants. The token map is emitted server-side by
[`components/branding/tenant-theme-style.tsx`](../../admin-ui/components/branding/tenant-theme-style.tsx) as an
inline `<style>` overriding the shadcn CSS vars for `:root` + `.dark` (no FOUC). `BrandingDialog` previews the
same `deriveTokens(...).dark` map against a mock UI before the operator commits.

---

## 7. Testing

Harness: [`admin-ui/vitest.config.ts`](../../admin-ui/vitest.config.ts) (jsdom, globals, `**/*.test.{ts,tsx}`,
`@/` alias) + [`admin-ui/vitest.setup.ts`](../../admin-ui/vitest.setup.ts) (jest-dom matchers, cleanup, Radix
DOM polyfills — `scrollIntoView`, pointer-capture, `matchMedia`). Scripts: `npm test` (`vitest run`),
`test:watch`, `test:report`. Playwright E2E is scaffolded but Phase 2.

~61 co-located tests (53 `.test.tsx`, 8 `.test.ts`). Per `frontend-admin.md` / `testing.md`, **`lib/` helpers
carry the 80% line-coverage gate** — they are pure and DOM-free, so they are cheap to cover and are where the
faceting / scope-matching / label logic that money & config flows depend on actually lives. Component tests
target the high-value interactive paths (dialogs, drawers, command palette) via Testing Library role queries,
mocking each route's `_actions` module — a component test never hits the backend.

---

## 8. Accuracy flags (as-built vs documented)

- **TanStack Table** is declared + named in the rules doc but unused — tables are hand-rolled (§1).
- **`frontend-admin.md`** still references `useFormState`/`useFormStatus` and a `lib/schemas/` folder; the
  as-built login uses React 19 `useActionState`, and validation is inlined per-form rather than centralised.
- The **`rules/` route tree** is a live-but-deprecated redirect shim (delete after one release cycle).
