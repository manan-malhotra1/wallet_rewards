# 007 — Soften two teleporting state changes (additive)

- **Status**: TODO
- **Commit**: c2e8746
- **Severity**: LOW (additive — adds motion where there is none, does not fix a defect)
- **Category**: Missed opportunities
- **Estimated scope**: 1 file (`app/(authenticated)/dashboard/_components/dashboard-client.tsx`)
- **Depends on**: 002 (reduced-motion gate). Prefer applying after 001 and 005.

## Problem

Two dashboard state changes currently **teleport** — content swaps with zero transition, which reads as a jump:

1. **Tenant switch.** The dashboard now hard-remounts on `key={activeTenantId}` (a correctness fix). The whole surface replaces instantly — a brief fade would explain the swap instead of blinking.
2. **Tile → trend metric change.** Clicking the Transactions / Volume / Revenue tile swaps the shared trend chart's series with no transition; the chart's shape jumps.

Both are seams where a short, subtle crossfade improves comprehension. This is additive polish, not a corrective finding — apply only if the snappier no-motion behavior isn't preferred.

Relevant code, `dashboard-client.tsx`: the returned root wrapper, and the trend-chart card:

```tsx
// root (after plan 005 this is a plain <div>; before 005 it carries the pending class)
return (
  <div>
    ...
    // the shared trend chart card:
    <Card className="...">
      <h2 ...>{trendLabel} over time</h2>
      {data.txnTimeseries ? (
        <TrendChart data={data.txnTimeseries} metric={trendMetric} selectedCurrencies={selectedCurrencies} currencyMeta={currencyMeta} />
      ) : null}
    </Card>
```

## Target

Use tw-animate-css (already imported in `app/globals.css` via `@import "tw-animate-css";`) `animate-in fade-in-0` classes — no new dependency. Keep both fades short (200ms) and opacity-only (no travel). Reduced-motion is handled globally by plan 002.

**1. Tenant-switch fade.** Because the component remounts on tenant change, `animate-in` fires on mount. Add it to the root element:

```tsx
return (
  <div className="animate-in fade-in-0 duration-200">
    ...
```

(If plan 005 is applied, this root is the plain outer `<div>`; add the classes there. If 005 is not yet applied, add them to whatever the single root element is — do not add a second root.)

**2. Trend-metric crossfade.** Give the `TrendChart` (or its immediate wrapper) a `key` bound to the metric so React remounts it on metric change, and let tw-animate fade it in:

```tsx
<div key={trendMetric} className="animate-in fade-in-0 duration-200">
  <TrendChart data={data.txnTimeseries} metric={trendMetric} selectedCurrencies={selectedCurrencies} currencyMeta={currencyMeta} />
</div>
```

Keep the `data.txnTimeseries ?` guard around it.

## Repo conventions to follow

- tw-animate-css `animate-in fade-in-0 duration-200` is the established enter-animation idiom in this repo (shadcn dialogs/selects use `data-[state=open]:animate-in ... fade-in-0`). Reuse it rather than hand-writing keyframes.
- Charts are guarded with `data.<field> ? <Chart/> : null` — preserve that guard.

## Steps

1. Add `animate-in fade-in-0 duration-200` to the `DashboardClient` root element (the outer `<div>` of the returned JSX).
2. Wrap the shared `TrendChart` render in a `<div key={trendMetric} className="animate-in fade-in-0 duration-200">…</div>`, keeping the existing `data.txnTimeseries ?` guard.

## Boundaries

- Do NOT add fades to the tiles, the other section charts, or the header — only the root (tenant switch) and the trend chart (metric swap). Over-animating a dashboard is itself a finding.
- Do NOT introduce Framer Motion or any dependency.
- Do NOT change chart internals, data flow, or `refetch`.
- If `trendMetric` / `TrendChart` no longer exist as named here (drift since c2e8746), STOP and report.

## Verification

- **Mechanical**: from `admin-ui/`, `npm run typecheck` (clean), `npm run build` (compiles).
- **Feel check** (this one genuinely needs eyes — a crossfade can look right in code and wrong live):
  - Switch tenants (sidebar): the new dashboard should **fade in over ~200ms**, not blink. It should not feel slow.
  - Click Transactions → Volume → Revenue tiles: the trend chart should **crossfade** between series rather than snapping. Confirm it does not re-run a long grow animation (plan 001 must be applied first, or the fade will stack on Recharts' 1500ms).
  - In DevTools, emulate `prefers-reduced-motion: reduce` and confirm both fades collapse to instant (via plan 002) — no lingering opacity ramp.
- **Done when**: tenant switch and trend-metric change both crossfade briefly, nothing else gained motion, and reduced-motion users get instant swaps.

## Author's note (uncertainty)

Whether these fades *improve* the dashboard or make it feel less snappy is a judgment call that can only be made live. If, on the feel check, the dashboard already felt crisp and correct after plans 001/005, it is legitimate to **skip this plan** — "no animation here" is a valid outcome for a dashboard.
