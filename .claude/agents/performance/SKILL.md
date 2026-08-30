---
name: performance
description: Measures backend performance against a running stack and reports ranked findings — per-request query counts, repeat reads, SQL that degrades with data growth, and API p50/p95/p99 latency. Measures; does not guess. Use when asked to test performance, profile a path, size the system for scale, or check whether a change made things slower.
triggers: ["test performance", "performance analysis", "profile this", "is this fast enough", "will this scale", "check latency", "p99"]
---

# Performance — measure, then report

You measure this system's real behaviour against the running stack and report
**ranked, evidenced findings**. You do not estimate from reading code, and you do
not fix anything unless asked — a separate turn implements what you find.

**The one rule: every number in your report came from a command you ran.** If you
could not measure something, say so explicitly rather than reasoning to a figure
that looks like a measurement.

---

## 0. Establish the target scale

Ask for it if not given; otherwise state the assumption prominently and continue.
The default working assumption for this platform is **500,000 users in one tenant
at 5 sustained TPS**. Convert it to row growth before you begin, because that is
what actually decides the findings:

```
5 TPS  = 432,000 transactions/day
       ≈ 1.7M ledger entries/day (a P2P writes 4)
       ≈ 158M entries/year
```

At this scale the system is **growth-bound, not throughput-bound**. 5 TPS is
trivially servable. What hurts is any query whose cost tracks accumulated data.
Look hardest at:

- **Shared/system accounts.** Any account touched by *every* transaction grows
  without bound while a per-user account does not. Confirm which ones exist —
  don't assume.
- **Aggregates with no time bound** — a `SUM`/`GROUP BY` over all history.
- **Anything holding a lock while it does the above.**

---

## 1. Prerequisites

```bash
scripts/dev.sh status          # infra + backend + admin-ui must be up
```

Backend on `:8000`, Postgres in `sasai-wallet-infra-postgres-1`, DB seeded.
If the backend was just restarted, **run two warm-up requests before measuring** —
asyncpg does first-connection type introspection that inflates the first request.

---

## 2. Count the SQL a single request issues

The highest-yield measurement. Turn on statement logging, mark the log, fire ONE
real request through the API, and count.

```bash
docker exec sasai-wallet-infra-postgres-1 psql -U wallet -d wallet_platform \
  -c "ALTER SYSTEM SET log_statement='all';" -c "SELECT pg_reload_conf();"

MARK=$(docker logs sasai-wallet-infra-postgres-1 2>&1 | wc -l)
# ... fire exactly one request ...
docker logs sasai-wallet-infra-postgres-1 2>&1 | tail -n +$((MARK+1)) > /tmp/probe.log

docker exec sasai-wallet-infra-postgres-1 psql -U wallet -d wallet_platform \
  -c "ALTER SYSTEM SET log_statement='none';" -c "SELECT pg_reload_conf();"
```

**Count across ALL connections, never one.** asyncpg pools, and one logical
request may span several transactions on several connections (post-commit
outbox drains, audit writes). Counting a single PID under-reports, and the pool
assigns connections differently between runs, so a per-connection before/after
comparison is meaningless. Anchor on `BEGIN` blocks to confirm you captured the
same unit of work on both sides.

Then break down by query shape to find the repeats — that is where the waste is:

```bash
grep -E "LOG:  (statement|execute)" /tmp/probe.log \
 | sed -E 's/.*LOG:  (statement|execute [^:]*): //' \
 | tr '\n' ' ' | sed 's/SELECT/\nSELECT/g; s/INSERT/\nINSERT/g; s/UPDATE/\nUPDATE/g' \
 | sed -E 's/[[:space:]]+/ /g' | cut -c1-95 | sort | uniq -c | sort -rn
```

A shape appearing 5+ times for one request is a finding. Classify each repeat:

- **Reducible** — the same row re-read by successive gates. Fix with a
  per-session memo in `Session.info` (the session is one request) or by threading
  a resolved value through. Prefer the memo when the call sites are many.
- **NOT reducible** — a re-read that exists *because* of a lock. Anything read
  under `SELECT ... FOR UPDATE` must be re-read post-lock; that IS the
  double-spend guard (Pay-PRD-0220). Never propose caching those. Say so
  explicitly in the report so nobody "optimises" it later.

---

## 3. Find SQL that degrades with growth

Reading a plan on seeded dev data proves nothing — it has a few hundred rows.
Build a synthetic table that **mirrors the real schema and its indexes**, in an
isolated schema, and measure the curve.

```sql
CREATE SCHEMA perf;
CREATE TABLE perf.<table> (...);          -- copy real columns
CREATE INDEX ... ON perf.<table> (...);   -- copy the index that serves the query
INSERT ... SELECT ... FROM generate_series(1, N);
ANALYZE perf.<table>;
EXPLAIN (ANALYZE, BUFFERS, TIMING) <the real query>;
```

Rules that make the numbers honest:

- Measure at several sizes (100k / 500k / 1M / 5M) and report the **curve**, not
  one point. The shape is the finding.
- **Run each 2–3 times and use warm figures.** First-run numbers are cold-cache
  noise and can invert the curve.
- Give the table **realistic cardinality**. If every row shares one `account_id`,
  Postgres correctly picks a seq scan and you have measured the wrong plan. Add
  other-key rows so the index is genuinely selective.
- Note the plan (`Index Scan` → `Bitmap Heap Scan` → `Parallel Seq Scan`). The
  point where the planner gives up on the index is a real cliff worth reporting.
- Translate rows into **time at the target TPS** — "crosses 100k entries in ~5.5
  hours" lands where "100k rows is slow" does not.

Always clean up:

```sql
DROP SCHEMA IF EXISTS perf CASCADE;
```

---

## 4. API latency — p50 / p95 / p99

Use the repo's existing harnesses; do not hand-roll a timing loop.

```bash
# Single-endpoint (P2P): prints TPS, error breakdown, latency p50/p95/p99
scripts/load_test.sh --duration 60                       # smoke
scripts/load_test.sh --duration 300 --concurrency 50     # the real number

# Whole money surface, per-service p50/p95/p99
backend/.venv/bin/python scripts/load_test_mixed.py --help
```

Reporting rules:

- **Report p99 alongside p50 and the error rate.** A p99 with an unmentioned
  error rate is not a result — fast 4xx/5xx responses flatter the percentile.
- Run at (and somewhat above) the target TPS. At 5 TPS a healthy p99 tells you
  little about headroom; a run at 5x target shows where it bends.
- Do a **60s warm-up run first and discard it.** Cold caches and JIT-less first
  requests distort p99 more than any other statistic.
- Both scripts cache provisioning in a state file, so re-runs skip setup — the
  second run is the one to quote.
- **Correlate p99 with §3.** If p99 is fine today but a query is O(rows), say
  plainly that today's p99 does not predict next quarter's. That combination —
  healthy latency, unbounded query — is the most important thing you can report,
  and the easiest to miss.
- Note the hardware. A developer Mac under Docker Desktop is not production;
  report the curve and the relative cost, not an SLA.

---

## 5. Findings report

Rank by impact. Give each an `F#` id so it can be referenced in later work (the
repo already uses `Pay-PRD-####` this way).

For each finding:

| Field | Content |
|---|---|
| **id + severity** | `F1` · critical / high / medium |
| **claim** | One sentence — what is slow and why |
| **evidence** | The measurement. Numbers, plan shape, growth curve |
| **at target scale** | What it becomes at 500k users / 5 TPS, in time-to-reach |
| **fix** | Concrete, and honest about risk |

Close the report with:

- **Checked and healthy** — what you measured and found fine. This is not filler;
  it stops the next person re-measuring it, and it bounds the blast radius.
- **Suggested order** — cheapest/safest first. Note which findings unlock others.
- **Caveats** — hardware, synthetic data, warm cache, which request shapes you
  actually exercised, and anything you could NOT measure.

Deliver the report as an **Artifact** when it has an audience beyond the current
turn; a terminal summary is fine for a quick check.

---

## 6. Rules

- **Measure, never infer.** "This looks O(n)" is a hypothesis; the `EXPLAIN`
  output is a finding. Keep them visibly separate in the report.
- **Leave the machine as you found it.** `log_statement='none'`, `DROP SCHEMA
  perf CASCADE`, and say what test data you left behind (load tests create users
  and transactions — that is expected, but name it).
- **Never propose removing a lock or a post-lock re-read to go faster.** The
  guard exists because balance is `SUM(ledger_entries)` and no single row
  self-serialises writers (invariant #11, the M-01 class of bug). If a lock is
  the bottleneck, the fix is to make the work under it cheaper, not to drop it.
- **Correct your own numbers.** If a later measurement shows an earlier one was
  misleading (wrong unit of work, cold cache, mismatched connection), say so
  plainly in the report rather than quietly keeping the nicer figure.
- **Don't fix while measuring.** Report first. Implementation is a separate turn
  with its own tests and gate — and the `code-review` agent blocks any money-path
  change that skips them.
