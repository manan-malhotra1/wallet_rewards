# TPS Monitoring & Load-Aware Bulk Execution — Design

**Date:** 2026-08-26
**Status:** Draft — awaiting review. No code written.
**Depends on:** [`2026-08-26-commission-wallet-design.md`](2026-08-26-commission-wallet-design.md) — this design gates the `commission_batches` runner defined there (D13–D16). It does not depend on the rest of that spec and can land first, with the gate wired in when the batch runner exists.
**Scope:** new `backend/app/modules/load_control/`, new `backend/app/shared/models/{observability,platform_settings}.py`, plus `backend/app/{main.py,config.py,celery_app.py}`, `backend/app/modules/{analytics,tenants,commission_batches}`, `admin-ui/app/(authenticated)/dashboard/`, `admin-ui/app/(authenticated)/tenants/`, `sasai-wallet-infra/`. Four Alembic migrations. One new Python dependency.

---

## 1. Problem

The platform has no idea how loaded it is.

Two services now in design — bulk commission disbursement and bulk commission
withdrawal (`commission_batches`, D13) — will post thousands of ledger rows in a
single run. Every one of those rows goes through `post_transaction`, which takes
`SELECT … FOR UPDATE` row locks on the wallet legs and the operator float
(invariant #11). A 5,000-row batch launched at 09:00 on payday competes directly
with live user traffic for the same connection pool and the same locks.

Measured load-testing evidence for how narrow the margin is: the P2P money path
plateaus at **~14–15 TPS** on the dev stack and *degrades* to ~12 TPS at
concurrency 50 with a p50 of 3.4s. Those numbers are a floor, not capacity — a
single `uvicorn --reload` process against SQLAlchemy's default 5+10 connection
pool — but they establish that the money path saturates at a low, measurable
number and that piling a bulk run on top of peak traffic is not a theoretical
concern.

Three things are missing:

1. **No load signal.** Nothing anywhere reports requests or transactions per
   second. `/metrics` is named in `.claude/rules/observability.md` as a Phase 2
   intention and does not exist.
2. **No history.** After an incident there is no way to answer "what was the
   platform doing at 02:00 last Tuesday?" other than reading application logs.
3. **No admission control.** Any approved batch runs immediately and to
   completion regardless of what else is happening.

## 2. What exists today (grounding)

| Thing | Where | Note |
|---|---|---|
| Redis client | `app/redis_client.py` | Process-singleton `redis.asyncio`, `decode_responses=True`. Already carries sessions, lockouts, rate limits |
| Fixed-window counters | `app/auth/rate_limit.py` | `INCR` + `EXPIRE` pattern for OTP and API-key limits. The TPS counter is the same shape, different key space |
| Celery + beat | `app/celery_app.py` | Two periodic jobs (`rewards.recon_sweep` 60s, `segments.recompute_all` hourly). Broker + backend are Redis |
| Analytics read layer | `app/modules/analytics/` | Read-only tenant-scoped aggregations, `_require_finance_or_admin` role gate, Pydantic DTOs |
| Dashboard panels | `admin-ui/app/(authenticated)/dashboard/_components/` | Hand-drawn SVG on `lib/chart-geometry.ts` + `plot-frame.tsx`. Server component fetch, client shell for interactivity |
| Tenant model | `app/shared/models/tenants.py` | `Tenant` plus a generic `TenantConfig` key/value child table |
| Config maker-checker | `app/modules/config_requests/` | Eight `CONFIG_TYPES`, all band-shaped money configs. `apply.py` dispatch is create / band-replace / delete-scope |
| `/metrics` | — | **Does not exist.** `prometheus-client` is not a dependency |
| Any TPS/QPS metric | — | **Does not exist** |
| Platform-scoped (non-tenant) config | — | **Does not exist.** Every config table carries `tenant_id` |

## 3. Decisions locked

| # | Decision | Rationale |
|---|---|---|
| D1 | TPS counts **all state-mutating API writes** (`POST/PUT/PATCH/DELETE` that reached a route handler), not just money-path transactions | Every write costs a DB round-trip and a pool slot. Restricting to `post_transaction` would miss registration bursts, config storms and OTP traffic that consume the same pool |
| D2 | Both **global** (all tenants) and **per-tenant** scopes are recorded. The bulk gate reads **global** | The connection pool and the row locks are shared. A quiet tenant's batch can still crush a busy one, so a per-tenant gate would be measuring the wrong thing |
| D3 | The **counter of record is Redis**; Prometheus and Postgres both derive from it | See §4. This is the decision that makes a single scrape target correct and keeps the gate's read sub-millisecond |
| D4 | **Prometheus** is the observability/alerting plane, exposed at `GET /metrics` | Chosen surface for alerting and Grafana. Derived at scrape time, so it adds nothing to the hot path |
| D5 | The **dashboard's 1-hour history reads Postgres** (`tps_samples`), not Prometheus | The panel follows the same server-component + analytics-module pattern as every other panel, and survives Prometheus being down. A product surface should not have an operational dependency on the monitoring stack |
| D6 | **Bulk-posted rows count toward TPS**, tagged `source="bulk"` | The gate must see real total load, otherwise two concurrent batches are invisible to each other and the dashboard understates DB load during a run |
| D7 | The gate uses **hysteresis**: a lower bar to start/resume, a higher bar to keep running | Direct consequence of D6. Without a band, a batch that counts its own rows pauses itself, sees the number fall, resumes, and oscillates |
| D8 | A batch is admitted only when **the off-hours window is open AND global TPS is under threshold** — both, ANDed, re-checked **before every chunk** | The window gives the operator a calendar guarantee; the TPS check handles the unexpected 02:00 spike. A start-only check lets a 5,000-row batch run into the morning peak |
| D9 | **Unknown load fails closed.** Redis unreachable → the gate refuses | Running a bulk batch blind is strictly worse than delaying it |
| D10 | On the request hot path a counter failure is **swallowed** | A metrics outage must never fail a payment. Surfaced as `sasai_tps_counter_errors_total` so the silence is visible |
| D11 | A blocked batch **retries indefinitely** — no expiry, no terminal starvation state | Nothing is ever silently lost and no operator action is required to recover. The cost is accepted and mitigated in §10 R2 by an age gauge + alert, not by a state change |
| D12 | Thresholds are **platform-level**; the off-hours window is **per-tenant** | The gate reads one global number, so one global bar. Tenants genuinely differ on when night is |
| D13 | Sample retention is **7 days** at 30-second resolution | ~100k rows at five tenants. Covers the dashboard view and last week's incident review. Prometheus keeps the longer, rolled-up copy |
| D14 | The **global** series is visible to `platform-admin` only. A tenant operator sees their own series plus a derived Quiet/Normal/Busy chip | Global TPS is cross-tenant information. The chip conveys everything a tenant operator needs to understand why their batch is waiting, without exposing another tenant's activity level |
| D15 | Sampling is **aligned to absolute 30s boundaries** and **idempotent** | Beat jitter must not produce ragged or duplicate buckets. The sampler derives its own bucket from the clock and upserts |

### Deviations from the options as originally posed

Three, all flagged before writing:

- **The per-tenant window does not go through config maker-checker.**
  `config_change_requests` has no tenant scope: all eight `CONFIG_TYPES` are
  band-shaped money configs and `apply.py`'s dispatch is built around
  create / band-replace / delete-scope. Three scalar columns on `tenants` do not
  fit that machinery, and bending them into it would mean a ninth config type
  whose "bands" are a single row. The window is edited on the existing Tenants
  page (platform-admin) and audit-logged instead — §7.2.
- **Platform-admin-editable thresholds need a home that does not exist.** There
  is no platform-scoped config table. §5.3 adds a minimal `platform_settings`
  KV table rather than making the thresholds deploy-time-only.
- **Prometheus is not the counter.** §4 explains why a pure-Prometheus topology
  needs either a Pushgateway or a per-Celery-worker exporter, and what is done
  instead.

## 4. Architecture — three planes

```
                    ┌──────────────────────────────────────────┐
   HTTP writes ────▶│                                          │
   (middleware)     │   REDIS  ── counter of record            │
                    │   tps:{scope}:{unix_second}   TTL 180s   │
   bulk rows  ─────▶│   tps:tenants:{bucket30}      TTL 180s   │
   (worker)         │   tps:totals (hash, monotonic)           │
                    └───────┬──────────────┬───────────────┬───┘
                            │              │               │
              scrape-time   │       beat/30s               │  per chunk
              derivation    │       aggregation            │  (sub-ms)
                            ▼              ▼               ▼
                     GET /metrics    tps_samples      bulk gate
                    (Prometheus)      (Postgres)      (Celery worker)
                            │              │               │
                            ▼              ▼               ▼
                    Grafana / alerts   dashboard      pause / resume
```

### 4.1 Why Redis is the counter and not Prometheus

The obvious build — `prometheus_client.Counter` in-process, scraped at
`/metrics` — does not survive contact with this deployment shape:

- **Celery workers have no HTTP server.** The bulk runner is exactly the process
  whose writes matter most (D6). Making it scrapeable means either starting a
  `start_http_server(port)` per worker process plus service discovery for a
  fleet that scales up and down, or pushing to a Pushgateway — which is the
  documented anti-pattern for this, and which would make the counter's meaning
  depend on push timing.
- **Multi-worker uvicorn splits the registry.** Each worker holds its own
  counter, so a scrape through a load balancer returns one worker's slice.
  Fixing it properly means `PROMETHEUS_MULTIPROC_DIR`, which brings its own
  operational sharp edges (a shared writable dir, stale files after an unclean
  restart, no working gauges without a mode selector).
- **The gate needs a synchronous answer.** Querying the Prometheus HTTP API
  before every chunk adds a network hop to the monitoring stack on a decision
  path, and inherits the scrape interval as read latency.

Putting the count in Redis — which every process already has a connection to —
removes all three problems at once. `/metrics` becomes a pure projection: a
custom collector that reads Redis at scrape time and emits the families. Because
nothing is held in process memory, **any API instance returns the same
platform-wide answer**, so the scrape target can be the service VIP and no
multiprocess directory is needed.

### 4.2 Key space

| Key | Type | TTL | Written by |
|---|---|---|---|
| `tps:global:{unix_second}` | counter | 180s | middleware, bulk worker |
| `tps:t:{tenant_id}:{unix_second}` | counter | 180s | middleware, bulk worker |
| `tps:tenants:{bucket30}` | set of tenant ids | 180s | middleware, bulk worker |
| `tps:totals` | hash: `src:http`, `src:bulk`, `t:{tenant_id}` | none | middleware, bulk worker |

`tps:tenants:{bucket30}` exists so the 30-second sampler knows which tenants to
write rows for without a `SCAN` over the keyspace. `bucket30 = (unix_second // 30) * 30`.

The platform-wide total is deliberately **not** a stored field — it is the sum of
the `src:*` fields, and storing it separately would be a second source of truth
that can drift. For the same structural reason the exposition carries two counter
names rather than one (§7.6): `sasai_write_ops_total` is labelled by `source` and
`sasai_tenant_write_ops_total` by `tenant_id`. One metric name cannot carry two
different label sets, and a `{source, tenant_id}` cross-product would need four
more hash fields on the hot path to answer a question nobody is asking.

`tps:totals` is monotonic and backs the Prometheus `_total` counters, so PromQL
`rate()` and `increase()` behave correctly over long windows. A Redis restart
resets it to zero; Prometheus detects counter resets natively, so this is
correct rather than merely tolerable.

### 4.3 Hot-path cost

One pipeline, one round-trip, eight commands:

```
INCR   tps:global:{sec}          EXPIRE tps:global:{sec} 180
INCR   tps:t:{tid}:{sec}         EXPIRE tps:t:{tid}:{sec} 180
SADD   tps:tenants:{b30} {tid}   EXPIRE tps:tenants:{b30} 180
HINCRBY tps:totals src:{source} 1     HINCRBY tps:totals t:{tid} 1
```

Measured expectation against local Redis: ~0.2–0.3 ms added to a request that
already spends milliseconds in Postgres. If profiling ever shows this on the
critical path, the pipeline collapses into a single `EVALSHA` Lua script — noted
as an available optimisation, not built now.

The tenant-scoped commands are skipped when the tenant is unknown; the global
ones always run.

### 4.4 Reading

```python
async def read_tps(scope: str, window_seconds: int = 30) -> TpsReading:
    """Rolling TPS over the last `window_seconds` COMPLETED seconds."""
    now = int(time.time())
    seconds = range(now - window_seconds, now)   # excludes the current partial second
    values = await redis_client.mget([f"tps:{scope}:{s}" for s in seconds])
    counts = [int(v) for v in values if v is not None]
    total = sum(counts)
    return TpsReading(
        ops=total,
        tps=Decimal(total) / window_seconds,
        peak_second=max(counts, default=0),
    )
```

One `MGET`, one round-trip. **The current second is deliberately excluded** — it
is still filling, and including it drags every reading downward by up to 1/30th
and makes the gate systematically optimistic.

`peak_second` is carried through everywhere because a 30-second average of 20
can conceal a one-second burst of 200, and the burst is what exhausts the pool.

## 5. Data model

### 5.1 `tps_samples` — new table

`backend/app/shared/models/observability.py`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid_pk` | |
| `tenant_id` | `UUID FK tenants.id NULL` | **NULL = platform-global.** The only nullable-tenant table in the schema; justified in the note below |
| `bucket_start` | `TIMESTAMP(tz) NOT NULL` | Aligned to an absolute 30-second boundary, UTC |
| `window_seconds` | `SmallInteger NOT NULL` | `server_default '30'`. Recorded so a future cadence change does not silently rescale history |
| `write_ops` | `Integer NOT NULL` | Raw count in the window |
| `tps` | `NUMERIC(10,2) NOT NULL` | `write_ops / window_seconds`, stored rather than derived so the dashboard query stays trivial |
| `peak_second_tps` | `Integer NOT NULL` | Max single-second count inside the window |
| `created_at` | `created_at_col()` | |

**Indexes:**

```python
Index("uq_tps_samples_global_bucket", "bucket_start",
      unique=True, postgresql_where=text("tenant_id IS NULL")),
Index("uq_tps_samples_tenant_bucket", "tenant_id", "bucket_start",
      unique=True, postgresql_where=text("tenant_id IS NOT NULL")),
Index("ix_tps_samples_bucket", "bucket_start"),
```

**Two partial unique indexes, not one composite.** A plain
`UniqueConstraint(tenant_id, bucket_start)` would not deduplicate the global
rows at all: Postgres treats NULLs as distinct, so a double beat fire would
insert two global rows for the same bucket and the chart would double-count.
The partial pair makes `ON CONFLICT DO NOTHING` correct for both shapes.

**On the nullable `tenant_id`** — invariant #7 says every *domain* table carries
`tenant_id`. `tps_samples` is operational telemetry about the platform, not
tenant domain data, and the platform-global series has no tenant by definition.
The alternative (a sentinel tenant row) would be worse: it would appear in the
tenant list, the tenant switcher and every `JOIN tenants`. Tenant-scoped rows are
still filtered by `tenant_id` on read exactly as the invariant requires; the
global row is only ever read by `platform-admin` (D14).

### 5.2 `commission_batches` — gate state (delta on the commission-wallet spec)

The lifecycle in that spec is `PENDING → APPROVED → APPLIED | APPLIED_PARTIAL`,
with `REJECTED` / `WITHDRAWN` terminal. Execution was instantaneous, so there was
no running state to model. It now has one:

```
PENDING → APPROVED → QUEUED → RUNNING ⇄ PAUSED → APPLIED | APPLIED_PARTIAL
```

`ck_commission_batches_status` gains `'QUEUED'`, `'RUNNING'`, `'PAUSED'`.
Terminal states are unchanged — the gate never terminates a batch (D11).

New columns:

| Column | Type | Notes |
|---|---|---|
| `queued_at` | `TIMESTAMP(tz) NULL` | Set on `APPROVED → QUEUED`. Backs the starvation-age gauge |
| `first_started_at` | `TIMESTAMP(tz) NULL` | First transition into `RUNNING` |
| `paused_reason` | `String(40) NULL` | `tps_above_threshold` / `outside_window` / `load_unknown` |
| `next_attempt_at` | `TIMESTAMP(tz) NULL` | What the UI shows the operator |
| `gate_pause_count` | `Integer NOT NULL` | `server_default '0'`. How much the batch fought the gate — the tuning signal for thresholds |
| `rows_posted` | `Integer NOT NULL` | `server_default '0'`. Progress, so a resumed batch reports honestly |

`rows_posted` is a progress counter for display only. The authoritative record of
what posted stays `commission_batch_rows.status = 'posted'` — one source of
truth for money, per the same reasoning that spec gives for not storing an
`approvals_received` counter.

### 5.3 `platform_settings` — new table

`backend/app/shared/models/platform_settings.py`

| Column | Type | Notes |
|---|---|---|
| `key` | `String(100) PRIMARY KEY` | e.g. `bulk_tps_pause_at` |
| `value` | `Text NOT NULL` | Stored as text, parsed by a typed accessor |
| `updated_by_admin_id` | `UUID NULL` | |
| `updated_at` | `updated_at_col()` | |

No `tenant_id` — that is the point of the table. Deliberately minimal: a typed
key registry in code (`KNOWN_SETTINGS: dict[str, type]`) validates writes, and an
unknown key is a 422 rather than a new row, so the table cannot become a
free-form dumping ground.

**Resolution order:** `platform_settings` row → `settings.py` value → hard-coded
default. Env therefore seeds the system and remains the disaster-recovery
fallback; a row overrides it at runtime.

**Cached in Redis for 30 seconds** (`platform_setting:{key}`), because the gate
reads thresholds before every chunk and must not add a Postgres round-trip to
that path. A write busts the cache immediately, so an operator sees their change
take effect at once rather than up to 30 seconds later.

Every write goes to `audit_log`. **No maker-checker**: these are operational
tuning knobs, not money configuration, and `config_change_requests` is
tenant-scoped and band-shaped (§3 deviations). If a threshold change later needs
four eyes, it becomes a ninth config type then.

### 5.4 `tenants` — three new columns

| Column | Type | Notes |
|---|---|---|
| `bulk_window_tz` | `String(64) NULL` | IANA name, e.g. `Africa/Johannesburg`. NULL → platform default |
| `bulk_window_start` | `Time NULL` | Local time |
| `bulk_window_end` | `Time NULL` | Local time |

All three NULL → the platform default window applies. Partially-set is rejected
at write with 422 `bulk_window_incomplete`; `start == end` means **always open**
(a 24-hour window) and is documented in the UI help text rather than left to be
discovered.

## 6. Module layout

```
backend/app/modules/load_control/
    __init__.py
    counter.py      # Redis increment + read primitives (no domain logic)
    middleware.py   # HTTP write counter
    metrics.py      # Prometheus custom collector
    service.py      # gate decision, threshold resolution, window arithmetic
    schemas.py      # Pydantic DTOs
    router.py       # platform-settings read/write (platform-admin)
    tasks.py        # sample_tps, prune_tps_samples
```

`counter.py` holds no business logic and is imported by both the middleware and
the Celery worker — it is the shared primitive, deliberately separate from
`service.py` so the gate's policy can be tested without Redis and the counter can
be tested without policy.

The `platform_settings` router lives here because thresholds are its only
consumer today; it lifts out to a `platform` module when a second unrelated
setting appears.

## 7. Components

### 7.1 Write counter middleware

Registered in `main.py`. Counts **on the way out**, after `call_next`, for two
reasons: the tenant is not known until a dependency has resolved the auth token,
and the status code is needed to apply the exclusions.

```python
COUNTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
EXCLUDED_PATHS = {"/healthz", "/metrics", "/"}
UNCOUNTED_STATUSES = {401, 403, 404, 405, 429}
```

- `401/403/429` never reached a handler — they cost auth work, not DB work.
- `404/405` never matched a route.
- **`409` IS counted.** An idempotency replay still did a lookup and a
  round-trip; pretending it was free understates real load.
- `5xx` IS counted. A request that blew up still consumed a pool slot, and
  excluding failures would make the meter read *quiet* precisely during an
  incident.

Tenant resolution, in order: `request.state.tenant_id` (set by the auth
dependencies — `get_current_admin`, the user-session dependency, and the API-key
authenticator each gain one assignment), else the `tenant_id` query parameter,
else global-only. Recording global-only when the tenant is unknown is correct:
the write happened, and the gate reads global.

The whole body is wrapped; on any Redis exception it increments an in-process
error counter and returns (D10).

### 7.2 Off-hours window

```python
def window_open(now_utc: datetime, tz_name: str, start: time, end: time) -> bool:
    """True when `now_utc` falls inside the tenant-local [start, end) window.

    A window whose end is not after its start wraps past midnight
    (22:00→04:00). start == end means always open.
    """
    if start == end:
        return True
    local = now_utc.astimezone(ZoneInfo(tz_name)).time()
    if start < end:
        return start <= local < end
    return local >= start or local < end
```

`zoneinfo` is stdlib on 3.12. The Docker image must carry the tz database —
`python:3.12-slim` does, but the Dockerfile gains an explicit `tzdata` install so
a base-image change cannot silently break window arithmetic in a way that only
shows up as batches running at the wrong hour.

DST is handled by `zoneinfo` and is not special-cased: on a spring-forward night
a 01:00–05:00 window is simply an hour shorter, which is the correct behaviour
and does not need code.

### 7.3 The gate

```python
@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str | None            # tps_above_threshold | outside_window | load_unknown
    current_tps: Decimal
    threshold: Decimal
    retry_after_seconds: int


async def check_bulk_admission(
    session: AsyncSession, *, tenant_id: UUID, is_resuming: bool
) -> GateDecision:
```

Evaluation order — window first, because it is free and a closed window makes the
Redis read pointless:

1. **Window closed** → `outside_window`, `retry_after` = seconds until the window
   opens (capped at `BULK_GATE_MAX_BACKOFF_SECONDS`, so a batch approved at noon
   wakes periodically rather than sleeping for thirteen hours in one Celery
   retry that a worker restart would lose).
2. **Redis read fails** → `load_unknown`, refuse (D9).
3. **TPS over bar** → `tps_above_threshold`, exponential backoff.
4. Otherwise allowed.

**The bar depends on which side you are approaching from (D7):**

| Situation | Bar | Default |
|---|---|---|
| Starting, or resuming after a pause | `BULK_TPS_RESUME_AT` | 25.0 |
| Continuing between chunks while running | `BULK_TPS_PAUSE_AT` | 40.0 |

A running batch tolerates more before backing off than a paused one needs to
restart. That band is what absorbs the batch's own contribution to the number
(D6) — without it, a batch adding 20 TPS to a 25 TPS bar pauses itself, watches
the number fall to 25, resumes, and thrashes.

### 7.4 Batch runner

```python
@shared_task(bind=True, max_retries=None)
def run_batch(self, batch_id: str) -> None:
    while rows_remain(batch_id):
        decision = check_bulk_admission(tenant_id=..., is_resuming=is_paused(batch_id))
        if not decision.allowed:
            mark_paused(batch_id, decision)          # PAUSED + reason + next_attempt_at
            raise self.retry(countdown=decision.retry_after_seconds)
        mark_running(batch_id)
        post_chunk(batch_id, size=BULK_CHUNK_SIZE)   # each row: counter.record(source="bulk")
    mark_terminal(batch_id)                          # APPLIED | APPLIED_PARTIAL
```

`max_retries=None` gives the indefinite retry of D11.

**Self-pacing.** Independent of the gate, the runner paces itself to
`BULK_SELF_TPS_CEILING` (default 20 rows/s) by sleeping between rows. This is a
belt-and-braces control that holds even when the measurement is wrong — if Redis
is lying, or the thresholds are badly tuned, the batch still cannot exceed a
known rate.

**Resumption is safe** because each row already carries its own idempotency key
and `commission_batch_rows.status` is the authoritative record. A worker killed
mid-chunk re-runs that chunk on retry; rows already `posted` are skipped, and any
that slip through are absorbed by the idempotency key (invariant #2). No
compensating logic is needed.

Backoff: `BULK_GATE_BACKOFF_SECONDS` (60) doubling to
`BULK_GATE_MAX_BACKOFF_SECONDS` (900), reset on a successful chunk.

Chunk size 50 bounds how long the batch can run past a spike: at the 20 rows/s
ceiling, a chunk is ≤2.5 s, so the worst case between gate checks is bounded and
small relative to the 30-second measurement window.

### 7.5 Sampler and pruner

`load_control.sample_tps` — Celery beat, every 30 s:

```python
now = int(time.time())
bucket = ((now // 30) * 30) - 30      # the last COMPLETED aligned window
```

The bucket is derived from the clock, never from when the task happened to fire,
so beat jitter cannot produce ragged buckets and a double fire produces the same
bucket. Rows are inserted `ON CONFLICT DO NOTHING` against the partial unique
indexes (D15). The 180-second key TTL leaves ample slack for a late run.

Tenants to write: members of `tps:tenants:{bucket}`. A tenant with no writes in
the window gets **no row** — absence means zero, and writing 2,880 zero rows a
day per idle tenant is noise. The dashboard query fills gaps with zero on read.

`load_control.prune_tps_samples` — daily at 03:00 UTC:
`DELETE FROM tps_samples WHERE bucket_start < now() - interval '7 days'` (D13).

### 7.6 Prometheus surface

`GET /metrics`, registered in `main.py`, guarded by a bearer token
(`settings.METRICS_TOKEN`); unset in local dev leaves it open, and the setting is
required in any non-local environment.

A custom `prometheus_client` collector reads Redis at scrape time and emits into
a **dedicated `CollectorRegistry` containing only the Sasai collectors** — no
default process collectors. Those would be per-uvicorn-worker (`process_cpu_seconds`
for whichever worker answered the scrape) and actively misleading behind a load
balancer. Excluding them is what makes any instance a valid scrape target.

| Metric | Type | Labels |
|---|---|---|
| `sasai_write_ops_total` | Counter | `source` (`http`\|`bulk`) |
| `sasai_tenant_write_ops_total` | Counter | `tenant_id` |
| `sasai_tps_current` | Gauge | `scope` (`global`\|`tenant`), `tenant_id` |
| `sasai_tps_peak_second` | Gauge | `scope`, `tenant_id` |
| `sasai_bulk_gate_open` | Gauge | `tenant_id` — 1 open, 0 closed |
| `sasai_bulk_batches` | Gauge | `state` |
| `sasai_bulk_batch_oldest_queued_seconds` | Gauge | — |
| `sasai_bulk_gate_pauses_total` | Counter | `reason` |
| `sasai_tps_counter_errors_total` | Counter | — |

Label cardinality is bounded by the tenant count (single digits). No per-route or
per-status labels here — `http_request_duration_seconds` from the observability
rules is a separate, later piece of work and is explicitly out of scope.

`sasai_tps_counter_errors_total` is the metric that says *the other metrics are
lying*, and it exists because D10 makes the failure silent by design.

`sasai_bulk_batches{state="QUEUED"}` and `..._oldest_queued_seconds` read
Postgres, not Redis; they are cached for 15 s inside the collector so a tight
scrape interval cannot turn `/metrics` into a load source of its own.

**Suggested alerts** (shipped as a commented `alerts.yml` alongside the compose
file, not wired to a receiver in this change):

| Alert | Condition |
|---|---|
| `SasaiTpsSustainedHigh` | `sasai_tps_current{scope="global"} > 40` for 10m |
| `SasaiBulkBatchStarving` | `sasai_bulk_batch_oldest_queued_seconds > 21600` (6h) |
| `SasaiTpsCounterBlind` | `increase(sasai_tps_counter_errors_total[5m]) > 0` |

### 7.7 Analytics endpoint

`GET /api/v1/analytics/tps?tenant_id={uuid}&window=1h`

Lives in the existing analytics router, reusing `_require_finance_or_admin`, and
additionally branches on `platform-admin` for the global series (D14).

```jsonc
{
  "as_of": "2026-08-26T14:30:00Z",
  "window_seconds": 30,
  "current": {
    "tenant_tps": 3.1,
    "global_tps": 12.4,          // null unless platform-admin
    "status": "quiet"            // quiet | normal | busy — always present
  },
  "thresholds": { "pause_at": 40.0, "resume_at": 25.0 },
  "bulk_window": { "tz": "Africa/Johannesburg", "start": "01:00", "end": "05:00", "open_now": false },
  "history": [
    { "bucket": "2026-08-26T13:30:00Z", "tenant_tps": 2.4, "global_tps": 9.1, "peak_second": 14 }
  ]
}
```

`status` is derived server-side from the global reading against the thresholds
(`< resume_at` → quiet, `< pause_at` → normal, else busy) and is returned to
**every** role. That is the mechanism of D14: a tenant operator learns why their
batch is waiting without learning how busy anyone else is.

`global_tps` and `history[].global_tps` are `null` for non-platform-admins. The
history is 120 points; missing buckets are zero-filled server-side so the chart
never has to reason about gaps.

`window` accepts `1h` only in this change. The parameter exists so `6h` / `24h`
can be added without a breaking change; anything else is 422
`invalid_analytics_parameter`, matching the existing analytics error shape.

### 7.8 Dashboard panel

New `dashboard/_components/tps-panel.tsx`, placed with the operational surfaces
near the attention strip — **not** among the money KPI tiles. TPS is an
operational metric and putting it beside revenue would misrepresent it as a
business number.

- Current TPS, large, with a Quiet / Normal / Busy chip using the existing
  `--pos` / `--warn` / `--neg` semantic trio.
- A 1-hour area chart, 120 points at 30 s.
- Two horizontal threshold rules (pause, resume) so an operator can see the
  headroom rather than infer it.
- A shaded vertical band for the tenant's bulk window when it intersects the
  hour, plus "next window opens in 4h 12m" as text when it does not.
- Poll every 30 s, aligned to the sample cadence.

Drawn hand-rolled on the existing `lib/chart-geometry.ts` + `plot-frame.tsx`
frame: fixed `VB_WIDTH = 1000` viewBox, `preserveAspectRatio="none"`, explicit px
height. That frame carries two non-negotiable consequences — every stroke needs
`vectorEffect="non-scaling-stroke"`, and all text (axis labels, the threshold rule
captions, tooltips) must be absolutely-positioned HTML overlays, because `<text>`
and `<circle>` distort under the horizontal stretch.

Colours come from the derived analytics tokens (`--grid`, `--zero-line`,
`--primary-line`, `--primary-tint`). No Tailwind opacity modifiers on them —
`color-mix()` values do not compose with `bg-token/50`.

The batch list gains a status column that renders `PAUSED` with its
`paused_reason` and `next_attempt_at` in plain language ("Waiting — platform busy,
retrying at 02:14"), so a waiting batch never looks stuck.

## 8. Configuration

`backend/app/config.py`:

```python
# --- TPS measurement -------------------------------------------------
TPS_WINDOW_SECONDS: int = 30
TPS_BUCKET_TTL_SECONDS: int = 180
TPS_SAMPLE_INTERVAL_SECS: int = 30
TPS_SAMPLE_RETENTION_DAYS: int = 7
METRICS_TOKEN: str | None = None          # required outside local dev

# --- Bulk admission control ------------------------------------------
BULK_TPS_PAUSE_AT: float = 40.0           # keep-running bar
BULK_TPS_RESUME_AT: float = 25.0          # start / resume bar (must be < PAUSE_AT)
BULK_CHUNK_SIZE: int = 50
BULK_SELF_TPS_CEILING: float = 20.0
BULK_GATE_BACKOFF_SECONDS: int = 60
BULK_GATE_MAX_BACKOFF_SECONDS: int = 900
BULK_WINDOW_DEFAULT_TZ: str = "UTC"
BULK_WINDOW_DEFAULT_START: str = "01:00"
BULK_WINDOW_DEFAULT_END: str = "05:00"
```

A model validator rejects `BULK_TPS_RESUME_AT >= BULK_TPS_PAUSE_AT` at startup —
inverting them silently disables the hysteresis and produces exactly the
oscillation D7 exists to prevent.

`BULK_TPS_PAUSE_AT` and `BULK_TPS_RESUME_AT` are the two keys in
`platform_settings.KNOWN_SETTINGS`; the rest are deploy-time.

**Local-dev overrides are mandatory to exercise this at all.** The dev stack
tops out around 15 TPS on the money path (§1), so defaults of 40/25 mean the gate
never closes and the whole feature appears to work by doing nothing. `.env.example`
ships `BULK_TPS_PAUSE_AT=8` / `BULK_TPS_RESUME_AT=5` with a comment explaining
why, and the seed sets a narrow bulk window on the dev tenant.

`sasai-wallet-infra/docker-compose.yml` gains a `prometheus` service scraping the
API every 15 s with the bearer token, plus `prometheus.yml` and a commented
`alerts.yml`. Grafana is **not** added — out of scope; Prometheus's own UI is
enough to validate the exposition.

New dependency: `prometheus-client>=0.21.0`. No other additions — `zoneinfo` is
stdlib and Redis, Celery and structlog are all already present.

## 9. Migrations

Numbered from the next free slot after the commission-wallet spec's two
migrations land; the numbers below are indicative.

| # | Migration | Contents |
|---|---|---|
| 1 | `tps_samples` | Table + three indexes (two partial unique) |
| 2 | `platform_settings` | Table |
| 3 | `tenant_bulk_window` | Three nullable columns on `tenants` |
| 4 | `commission_batch_gate_state` | Six columns + `ck_commission_batches_status` extension. **Depends on the commission-wallet migration** |

Migrations 1–3 are independent of the commission-wallet work and can land first;
4 is the join point. All are additive — every new column is nullable or carries a
`server_default`, so there is no backfill and no downtime.

`python scripts/check_migrations.py` before commit, per invariant #3.

### Delivery order

The work splits into three independently shippable slices, in this order:

1. **Measurement** — counter, middleware, `tps_samples`, sampler, pruner,
   `/metrics`, Prometheus compose service. Ships a working TPS number and
   history with no behaviour change anywhere. Independently valuable: it answers
   §1's questions 1 and 2 on its own.
2. **Surfacing** — `platform_settings`, tenant window columns, the analytics
   endpoint, the dashboard panel, the Tenants-page window editor. Still no
   gating; an operator can now see load, thresholds and windows.
3. **Gating** — `check_bulk_admission`, the batch-runner loop, migration 4.
   Requires the commission-wallet batch runner to exist.

Slices 1 and 2 have no dependency on the commission-wallet work and can land
while it is still in review.

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Self-oscillation** — the batch counts its own rows, pauses itself, resumes, thrashes | Hysteresis band (D7) plus the independent `BULK_SELF_TPS_CEILING`. `gate_pause_count` per batch is the tuning signal: a batch with dozens of pauses means the band is too narrow |
| R2 | **Starvation** — indefinite retry (D11) means a permanently busy platform leaves month-end commission silently unpaid | `queued_at` → `sasai_bulk_batch_oldest_queued_seconds`, alert at 6h, an entry in the dashboard attention strip, and `next_attempt_at` shown on the batch row. Visibility, not expiry — the decision stands, the silence does not |
| R3 | **A 30 s average lags a spike by up to 30 s** | Chunk size 50 at ≤20 rows/s bounds the over-run to ~2.5 s. If that proves too slow in practice, add a second 5-second fast-check ANDed with the 30-second one — the counter already supports any window |
| R4 | **Redis is now on the money hot path** | Errors swallowed (D10), surfaced as `sasai_tps_counter_errors_total` with an alert on any occurrence. The gate fails closed (D9), so a blind platform delays batches rather than flooding |
| R5 | **The metric weighs a config write the same as a ledger post** — a direct consequence of D1 | The threshold is a proxy, and is honest about it. `tps_samples` history is the tuning input, and `peak_second_tps` guards against a burst averaged away. If the proxy proves too coarse, the `source` label already partitions the counter and a weighted variant is additive |
| R6 | **Cross-tenant information disclosure** via the global series | D14 — global numbers are `platform-admin` only; tenant operators get the derived chip |
| R7 | **Default thresholds are above what the dev stack can generate** | §8 dev overrides, and the defaults are re-baselined against a real multi-worker measurement before production. Until that measurement exists, 40/25 are placeholders, and the spec says so rather than implying they are calibrated |
| R8 | **`/metrics` leaks operational shape if unauthenticated** | Bearer token, required outside local dev. Tenant labels are UUIDs, never names; no PII, no amounts |

## 11. Testing

Per `.claude/rules/testing.md` and the CLAUDE.md mandate that every backend
interface carries automation tests. Written by the `automation-testing` agent.
Redis is faked; the clock is `freezegun`.

**Counter (`counter.py`)**
- Window sum excludes the current partial second.
- `peak_second` returns the max, not the mean.
- Missing keys (expired mid-window) are treated as zero, not an error.
- A Redis exception on write is swallowed and increments the error counter.
- A Redis exception on read raises, so the gate can fail closed.

**Middleware**
- `POST/PUT/PATCH/DELETE` increment; `GET/HEAD/OPTIONS` do not.
- `/healthz`, `/metrics`, `/` are excluded.
- `401/403/404/405/429` are not counted; `409` and `500` are.
- Tenant attribution: from `request.state`, falling back to the query param,
  falling back to global-only.

**Window arithmetic**
- Non-wrapping (01:00–05:00) inside, outside, and on both boundaries.
- Wrapping (22:00–04:00) at 23:00, 03:00, 05:00.
- `start == end` → always open.
- Two tenants in different timezones at the same UTC instant get opposite answers.
- DST spring-forward night: the window is an hour shorter and does not except.

**Gate**
- Window closed → `outside_window`, and TPS is never read.
- Redis down → `load_unknown`, `allowed=False`.
- Hysteresis: at TPS 30 a *resuming* batch is refused and a *running* batch is
  allowed — the table in §7.3 asserted directly.
- Backoff doubles to the cap and resets after a successful chunk.
- Startup validator rejects `RESUME_AT >= PAUSE_AT`.

**Sampler**
- Bucket alignment: firing at `:07` and at `:29` both write the `:00` bucket.
- Idempotent: running twice for one bucket leaves one global row **and** one row
  per tenant — the partial-index case that a naive composite unique would miss.
- A tenant absent from `tps:tenants:{bucket}` gets no row.
- Pruner deletes beyond 7 days and nothing inside it.

**Batch runner (integration)**
- Starts under threshold, TPS spikes mid-run → `PAUSED` with
  `tps_above_threshold`, retry scheduled, `rows_posted` reflects only what posted.
- TPS drops → resumes, completes, and **no row is posted twice** (the resumption
  correctness claim in §7.4, asserted against the ledger).
- Worker killed mid-chunk → on retry, `posted` rows are skipped.
- Approved outside the window → `QUEUED`, never enters `RUNNING`.
- Self-pace ceiling holds when the gate is wide open.

**Analytics endpoint**
- Role gate: neither `finance-reviewer` nor `platform-admin` → 403.
- `platform-admin` sees `global_tps`; `finance-reviewer` gets `null` **and still
  gets `status`** — the D14 contract.
- Tenant A's token cannot read tenant B's series.
- 120 points, gaps zero-filled.
- `window=2h` → 422.

**Prometheus**
- `/metrics` returns valid exposition format and parses with the client's parser.
- Wrong/missing token → 401 when `METRICS_TOKEN` is set; open when unset.
- The registry emits no default process collectors.
- Two API instances backed by one Redis return identical TPS values — the
  claim in §4.1 that any instance is a valid scrape target.

## 12. Out of scope

Named so they are not assumed:

- `http_request_duration_seconds` and the rest of the observability-rules metric
  set. This change adds `/metrics`; populating it fully is separate work.
- Grafana dashboards and alert receivers. Alert *rules* ship commented.
- Kafka consumer lag metrics.
- Auto-tuning thresholds from history.
- TPS-based admission control on anything other than bulk batches. Live user
  traffic is never rejected by this gate; API-key rate limiting already exists
  for that and is unchanged.
- Rolling `tps_samples` up to a coarser long-term tier. Prometheus holds the
  long-term copy.
