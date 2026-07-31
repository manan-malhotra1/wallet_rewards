# 005 — Stop the whole dashboard flashing on every refetch

- **Status**: DONE (7b8fab0)
- **Commit**: c2e8746
- **Severity**: MEDIUM
- **Category**: Cohesion & feel
- **Estimated scope**: 1 file (`app/(authenticated)/dashboard/_components/dashboard-client.tsx`)

## Problem

During a refetch (any range or granularity change) the **entire** dashboard — title, currency toggle, time switcher, tiles, and every chart — dims to 60% opacity. `dashboard-client.tsx:115`:

```tsx
return (
  <div className={pending ? "opacity-60 transition-opacity" : "transition-opacity"}>
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-xl font-bold tracking-tight">Overview</h1>
      <div className="flex flex-wrap items-center gap-3">
        <CurrencyToggle ... />
        <TimeRangeSwitcher ... />
      </div>
    </div>
    {/* ---- Overview tiles ---- */}
    ...
```

Two problems: (1) the controls you just clicked (the time switcher / toggle) dim under your cursor, which feels like the UI went unresponsive; (2) dimming *everything* reads as a full-page flash on every interaction. The pending state should signal "the data is updating" without flashing the chrome.

## Target

Keep the header (title + `CurrencyToggle` + `TimeRangeSwitcher`) at **full opacity always**, and apply the pending dim only to the **data region** (tiles + all sections). Soften the dim from `opacity-60` to `opacity-70`, keep the short opacity transition, and add `aria-busy` + `pointer-events-none` on the data region while pending so stale content can't be clicked mid-update.

Structure after the change:

```tsx
return (
  <div>
    {/* header stays crisp — never dims */}
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-xl font-bold tracking-tight">Overview</h1>
      <div className="flex flex-wrap items-center gap-3">
        <CurrencyToggle ... />
        <TimeRangeSwitcher ... />
      </div>
    </div>

    {/* only the data dims while refetching */}
    <div
      aria-busy={pending}
      className={
        pending
          ? "pointer-events-none opacity-70 transition-opacity duration-200 ease-out"
          : "transition-opacity duration-200 ease-out"
      }
    >
      {/* ---- Overview tiles ---- */}
      ...everything that is currently below the header...
    </div>
  </div>
);
```

## Repo conventions to follow

- `dashboard-client.tsx` is the `"use client"` shell; `pending` comes from the existing `useTransition()` (`const [pending, startTransition] = useTransition()`). Do not change the transition/refetch logic — only where the `pending` class is applied.
- Tailwind `duration-200 ease-out` matches the duration scale used elsewhere in this plan set.

## Steps

1. Open `dashboard-client.tsx`. In the returned JSX, change the outermost wrapper `<div className={pending ? "opacity-60 transition-opacity" : "transition-opacity"}>` into a plain `<div>` (no pending class).
2. Leave the header `<div className="mb-4 flex flex-wrap items-center justify-between gap-3">…</div>` as the first child of that plain `<div>`, unchanged.
3. Wrap **everything after the header** (starting at the `{/* ---- Overview tiles ---- */}` grid through the last section) in a new `<div aria-busy={pending} className={pending ? "pointer-events-none opacity-70 transition-opacity duration-200 ease-out" : "transition-opacity duration-200 ease-out"}>`. Close it before the outer `</div>`.
4. Confirm JSX still has exactly one root element.

## Boundaries

- Do NOT change tile/chart components, data flow, `refetch`, or `useTransition` usage.
- Do NOT move the header's controls or change their props.
- Do NOT add dependencies.
- If the current outer wrapper is not the `opacity-60 transition-opacity` div described above (drift since c2e8746), STOP and report.

## Verification

- **Mechanical**: from `admin-ui/`, `npm run typecheck` (clean), `npm run build` (compiles).
- **Feel check**: run the app, open `/dashboard`, toggle range/granularity repeatedly. Confirm the **title, currency chips, and time switcher never dim** — only the tiles/charts fade slightly (~70%) and can't be clicked while updating, then return. The interaction should feel like the data is refreshing, not like the page blinked.
- **Done when**: the header stays at full opacity during `pending`, and the data region carries `aria-busy` + the softened dim.
