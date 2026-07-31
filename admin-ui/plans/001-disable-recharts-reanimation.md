# 001 — Stop dashboard charts re-animating on every filter change

- **Status**: DONE (446ed90)
- **Commit**: c2e8746
- **Severity**: HIGH
- **Category**: Purpose & frequency / Easing & duration
- **Estimated scope**: 8 files, one prop added per chart series element (~20 edits)

## Problem

Every chart on the dashboard uses Recharts with its default animation: `isAnimationActive` defaults to `true`, `animationDuration` defaults to **1500ms**, `animationEasing` to `"ease"`. The dashboard re-fetches and re-renders on **every** time-range change, granularity change, currency-toggle change, and tenant switch. On each of those, all charts replay a 1.5-second grow/draw animation.

Per the audit rules: UI animations must stay **under 300ms**, and motion on a high-frequency surface (a dashboard you filter constantly) should be removed or drastically reduced. A crisp analytics dashboard should **snap** to new data, not perform a 1.5s reveal each time you nudge a filter.

None of the chart files set the animation props. Affected files (all under `app/(authenticated)/dashboard/_components/`):

```
trend-chart.tsx        — <Area>, <Line> (count mode: Area + Line; money mode: one <Line> per currency + previous <Line>)
service-mix-chart.tsx  — <Pie>
status-breakdown-chart.tsx — <Bar> ×3 (completed/failed/pending)
users-growth-chart.tsx — <Bar>, <Line>
revenue-chart.tsx      — <Bar> (one per currency, mapped)
rewards-chart.tsx      — <Line> ×2 (issued/redeemed)
net-flow-chart.tsx     — <Bar> ×2 (inflow/outflow)
user-type-chart.tsx    — <Pie>
```

Example current code (`trend-chart.tsx`, count mode):

```tsx
<Area type="monotone" dataKey="current" name="Transactions" stroke={CHART_SERIES[0]} fill="url(#trendFill)" strokeWidth={2} />
<Line type="monotone" dataKey="previous" name="Previous period" stroke={CHART_SERIES[1]} strokeDasharray="4 4" strokeWidth={1.5} dot={false} />
```

## Target

Add `isAnimationActive={false}` to every Recharts series element (`<Area>`, `<Line>`, `<Bar>`, `<Pie>`) in all eight files. Charts then render and update instantly — the correct behavior for a frequently-filtered dashboard.

```tsx
<Area type="monotone" dataKey="current" name="Transactions" stroke={CHART_SERIES[0]} fill="url(#trendFill)" strokeWidth={2} isAnimationActive={false} />
<Line type="monotone" dataKey="previous" name="Previous period" stroke={CHART_SERIES[1]} strokeDasharray="4 4" strokeWidth={1.5} dot={false} isAnimationActive={false} />
```

Do NOT set a non-zero `animationDuration` instead — the goal is *no* replay on data change, not a shorter one. (If a one-time entrance reveal is ever wanted, that is a separate, deliberate decision — not this plan.)

## Repo conventions to follow

- Charts are presentational client components in `app/(authenticated)/dashboard/_components/*-chart.tsx`, each starting with `"use client";`. Only add the `isAnimationActive` prop — do not restructure.
- Colors come from `@/lib/chart-colors` (`CHART_SERIES`, `seriesColor`, `STATUS_COLORS`) — leave them untouched.

## Steps

For each of the eight files above, add `isAnimationActive={false}` to **every** `<Area>`, `<Line>`, `<Bar>`, and `<Pie>` element (including the ones created inside `.map(...)` in `revenue-chart.tsx`, `trend-chart.tsx` money mode, `net-flow-chart.tsx`, and the two `<Pie>` donuts):

1. `trend-chart.tsx` — the count-mode `<Area>` + `<Line>`, and every money-mode `<Line>` (the `series.map(...)` lines and the single-currency `__prev` `<Line>`).
2. `service-mix-chart.tsx` — the `<Pie>`.
3. `status-breakdown-chart.tsx` — all three `<Bar>` elements.
4. `users-growth-chart.tsx` — the `<Bar>` and the `<Line>`.
5. `revenue-chart.tsx` — the `<Bar>` inside `currencies.map(...)`.
6. `rewards-chart.tsx` — both `<Line>` elements.
7. `net-flow-chart.tsx` — both `<Bar>` elements (inflow/outflow).
8. `user-type-chart.tsx` — the `<Pie>`.

## Boundaries

- Do NOT touch any non-chart file, data logic, colors, axes, tooltips, or layout.
- Do NOT add `animationDuration`/`animationEasing` — only `isAnimationActive={false}`.
- Do NOT add dependencies.
- If a chart file's element set differs from the list above (drift since commit c2e8746), STOP and report.

## Verification

- **Mechanical**: from `admin-ui/`, `npm run typecheck` (clean) and `npm run build` (compiles).
- **Feel check**: run the app, open `/dashboard`. Toggle 7d → 30d, then Day → Week, then flip a currency chip. Confirm every chart **updates instantly with no grow/draw sweep**. Switch tenants (sidebar) and confirm charts appear already-drawn, not animating in.
- **Done when**: no chart plays a multi-hundred-ms animation on any filter change; `grep -rL "isAnimationActive" app/(authenticated)/dashboard/_components/*-chart.tsx` returns nothing (every chart file references the prop).
