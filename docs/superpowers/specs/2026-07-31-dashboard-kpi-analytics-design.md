# Dashboard KPI & Analytics — Design

**Date:** 2026-07-31
**Author:** Manan (with Claude)
**Status:** Draft for review

## 1. Problem

The current dashboard (`admin-ui/app/(authenticated)/dashboard/page.tsx`) shows only
operational queues — pending reconciliation, manual-review count, and the last 10 audit
events. It does **not** communicate what the product actually is or how it is performing:
no transaction trends, no growth, no revenue, no rewards activity. A stakeholder opening
the admin cannot answer "how is the wallet doing this week vs last?".

We are rebuilding the dashboard into an **interactive KPI dashboard** with graphs and
period-over-period comparison (day-on-day, week-on-week), backed by **real tenant-scoped
analytics endpoints**.

Decisions locked in brainstorming:
- **Real backend analytics API** (not mock data).
- **All KPI groups** in scope (Transaction activity, Users/growth, Revenue, Rewards & liquidity).
- **Rich & interactive** fidelity — clickable tiles driving a shared chart, previous-period
  comparison overlays, a global time-range + granularity switcher.

## 2. Data foundation (what already exists)

All aggregation reads existing tables via SQLAlchemy ORM (no raw SQL, `tenant_id`-filtered
per invariant 4 & 7). No new domain tables are required.

| Source table | Powers | Key columns |
|---|---|---|
| `transactions` | Activity (A), Revenue (D) | `transaction_type`, `status`, `amount`, `fee_amount`, `commission_amount`, `tax_amount`, `currency`, `created_at`, `initiated_by` |
| `users` | Users/growth (B) | `user_type`, `status`, `created_at` |
| `ledger_entries` | Money/liquidity (C) | `entry_type`, `amount`, `status`, `account_id` |
| `redemptions` | Rewards (E) | `status`, `points_amount`, `created_at` |
| `rewards` (points issuance) | Rewards (E) | issuance rows |

`transactions` is the workhorse — a single tenant-scoped table with per-row type, status,
amount, and the three revenue components. Grouping it by `date_trunc(granularity, created_at)`
yields nearly every group-A and group-D series.

## 3. KPI catalogue

Each KPI names its source and comparison. "Compare" = current period value plus a delta vs
the immediately preceding equal-length period (this is the DoD / WoW ask, expressed as a
delta chip on tiles and a dotted previous-period overlay on trend charts).

### Group A — Transaction activity
| # | KPI | Viz | Compare |
|---|---|---|---|
| A1 | Total transactions | stat tile + sparkline | DoD / WoW % |
| A2 | Transaction volume (value, base currency) | stat tile + sparkline | DoD / WoW % |
| A3 | Transactions over time | area/line, Day/Week/Month toggle | prev-period overlay |
| A4 | Mix by service type | donut + stacked bar | — |
| A5 | Average transaction value | stat tile + trend | WoW % |
| A6 | Success / failed / pending | stacked bar + success-rate % headline | — |

### Group B — Users / growth
| # | KPI | Viz | Compare |
|---|---|---|---|
| B1 | Total registered users | stat tile | quarterly growth % |
| B2 | Registered yesterday / this week | stat tile secondary line | — |
| B3 | New registrations over time | bar, Day/Week/Quarter toggle | prev-period overlay |
| B4 | Active users (DAU / WAU / MAU) | stat tiles + DAU/MAU stickiness ratio | trend |
| B5 | New vs returning transacting users | grouped bar | — |
| B6 | Users by type (consumer/agent/merchant…) | donut | — |

### Group C — Money & liquidity
| # | KPI | Viz | Compare |
|---|---|---|---|
| C1 | Total wallet balances held (float liability) | stat tile | — |
| C2 | Cash float health (`system_cash_inflow` vs low-water) | gauge / tile with threshold | — |
| C3 | Net flow (inflow vs outflow per period) | in/out bars | — |

### Group D — Revenue
| # | KPI | Viz | Compare |
|---|---|---|---|
| D1 | Fees + tax + commission earned | stat tile + sparkline | WoW % |
| D2 | Revenue by service type | bar | — |

### Group E — Rewards
| # | KPI | Viz | Compare |
|---|---|---|---|
| E1 | Points issued vs redeemed | dual line | — |
| E2 | Outstanding points liability | stat tile | — |
| E3 | Redemption pending / throughput | tile (retains existing operational widget) | — |

### Group F — Operations health (retained)
Pending recon, manual review, open exceptions — kept from the current dashboard, moved into
a compact "needs attention" strip so the page still doubles as an ops cockpit.

## 4. Backend design — analytics module

New module `backend/app/modules/analytics/` — **read-only**, no ledger writes, so it does not
touch the money-path invariants beyond the standard tenant-scoping rule.

```
analytics/
  router.py     # GET endpoints, tenant resolved from auth token
  service.py    # ORM aggregation queries (grouped by date_trunc)
  schemas.py    # Pydantic v2 response models
```

### Endpoints (all tenant-scoped, all take `range` + `granularity` query params)

| Endpoint | Returns |
|---|---|
| `GET /analytics/summary` | All stat-tile scalars for the current period + previous-period value for each (so the frontend computes deltas). Groups A/B/D/E headline numbers in one round-trip. |
| `GET /analytics/transactions/timeseries` | `[{ bucket, count, volume }]` per bucket, plus a parallel previous-period array for the overlay. |
| `GET /analytics/transactions/by-service` | `[{ service_type, count, volume }]` for the donut/bar. |
| `GET /analytics/transactions/by-status` | `[{ bucket, completed, failed, pending }]`. |
| `GET /analytics/users/timeseries` | new-registration counts per bucket + prev-period. |
| `GET /analytics/users/active` | DAU/WAU/MAU + stickiness. |
| `GET /analytics/revenue/by-service` | `[{ service_type, fee, tax, commission, total }]`. |
| `GET /analytics/rewards/timeseries` | points issued vs redeemed per bucket + outstanding liability. |

**Query params (shared):** `range` ∈ {`24h`,`7d`,`30d`,`quarter`}, `granularity` ∈
{`day`,`week`,`month`}. The service maps `range` → a start datetime and derives the equal-length
previous window for comparison.

**Aggregation approach:** SQLAlchemy `func.date_trunc(granularity, created_at)` grouping with
`func.count`, `func.sum`. All filtered by `tenant_id`. No raw SQL. Amounts summed in the
transaction's `currency`; Phase-1 assumption is a single base currency per tenant (matches the
per-tenant `base_currency` provisioning), so no FX conversion — documented as a known limitation.

**Performance:** existing indexes `ix_transactions_status (status, tenant_id)` and the
`(tenant_id, created_at)` index cover the grouping. If a date-bucket index proves necessary
after measuring, it is added via Alembic (invariant 3). No premature index.

**Auth:** same Keycloak dependency as other admin routers; read requires an authenticated admin.

### Tests (per coding guidelines §3 — every endpoint)
Happy path, 401 (unauth), tenant isolation (tenant B sees zero of tenant A's transactions),
and empty-range (new tenant → all-zero series, no crash). Aggregation correctness: seed N
transactions across buckets, assert the counts/sums per bucket. These live in
`backend/tests/analytics/`.

## 5. Frontend design — dashboard rebuild

### Library
Add **Recharts** (composable, SSR-friendly, themeable). Charts read colors from the existing
OKLab brand palette (`lib/brand-palette.ts`) via CSS variables so they respect per-tenant
branding and dark/light mode.

### Component structure
```
dashboard/
  page.tsx                     # server component: reads active tenant, renders shell
  _components/
    dashboard-client.tsx       # 'use client' — owns time-range + selected-tile state
    time-range-switcher.tsx    # Today / 7d / 30d / Quarter + Day/Week/Month
    stat-tile.tsx              # big number + sparkline + delta chip; clickable
    kpi-tile-row.tsx           # the top row of clickable tiles
    trend-chart.tsx            # the shared main chart with prev-period overlay
    service-mix-chart.tsx      # donut + stacked bar
    status-breakdown-chart.tsx # success/failed/pending
    users-growth-chart.tsx
    revenue-chart.tsx
    rewards-chart.tsx
    attention-strip.tsx        # retained ops widgets (recon/manual review/exceptions)
```

### Interaction model
- **Global switcher** at top sets `range` + `granularity` in URL params (shareable view,
  matches the repo's "URL params for filter state" convention). Changing it refetches via
  a server action and re-renders all charts.
- **Clickable stat tiles:** selecting a tile (e.g. "Volume") swaps the shared `trend-chart`
  to that metric's series. Selected state is client state; default = Total transactions.
- **Previous-period overlay:** every trend chart draws a solid current-period line and a
  dotted previous-period line — the visual week-on-week / day-on-day comparison.
- **Delta chips:** green ▲ / red ▼ with % vs previous period, computed from the
  `/analytics/summary` current+previous scalars.

### Data fetching
Server component fetches the initial `/analytics/summary` + default timeseries. The client
component calls a server action (`_actions.ts`) for subsequent range/granularity changes —
never fetches the backend directly from the browser (frontend rule). Typed client functions
added to `lib/api-endpoints.ts` (`getAnalyticsSummary`, `getTransactionsTimeseries`, …) with
matching types in `lib/api-types.ts`.

### Loading & empty states
Skeleton tiles + chart placeholders while fetching. New tenant with no data → friendly
"No activity yet in this range" empty states per chart, not errors. Backend-unreachable →
existing `ErrorBanner` pattern.

### Frontend tests (guidelines §4 — active)
- `lib` helpers: delta/percent-change formatter, range→label mapping — unit tested.
- Key component: `stat-tile` (renders value + correct delta direction), `time-range-switcher`
  (fires change with correct params). Server action mocked; no backend calls.

## 6. Out of scope (this cut)
- Multi-currency FX normalization (single base currency per tenant assumed).
- Cross-tenant / platform-wide roll-up (admin sees active tenant only).
- Real-time streaming/websocket updates (page fetches on load + on range change).
- Export to CSV/PDF, scheduled email reports.
- Materialized-view / pre-aggregation caching — added only if measured query latency requires it.

## 7. Build order (for the plan)
1. Backend `analytics` module: schemas → service (aggregations) → router → tests.
2. Frontend: add Recharts; typed API client fns + types.
3. Frontend: stat tiles + time-range switcher + shared trend chart (group A first).
4. Frontend: remaining charts (B, D, C, E) + retained attention strip.
5. Frontend tests; wire everything through the server action; polish loading/empty states.
