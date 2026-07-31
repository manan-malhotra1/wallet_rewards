# 002 — Add global prefers-reduced-motion support

- **Status**: DONE (ca2db9c)
- **Commit**: c2e8746
- **Severity**: HIGH
- **Category**: Accessibility
- **Estimated scope**: 1 file (`app/globals.css`), one media block

## Problem

The app honors `prefers-reduced-motion` nowhere — a repo-wide grep returns **zero** matches. Users who set "reduce motion" at the OS level still get: tw-animate-css enter/exit on dialogs, selects, dropdowns, popovers and tooltips (`data-[state=open]:animate-in ... zoom-in-95`), the `animate-pulse` status pills (`components/ui/status-pill.tsx:123,144`), and `animate-spin` loaders. There is no escape hatch.

Per the audit: reduced motion means *fewer and gentler* animations — drop position/scale movement, keep opacity/color feedback so the UI stays comprehensible.

Current `app/globals.css` imports tw-animate and defines only color tokens in `@theme inline`; it has no motion / accessibility block.

## Target

Add one media block to `app/globals.css` (after the `@import "tw-animate-css";` line, near the top so it is easy to find). It near-instantly completes transitions and animations for reduced-motion users while leaving opacity/color changes effectively instant rather than jarringly moving:

```css
/* Respect the user's reduced-motion preference: keep feedback, drop movement.
   tw-animate-css enter/exit (zoom/slide), pulse, spin, and any transform
   transitions collapse to ~instant; opacity/color still change, just without
   the travel. */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

Note on charts: Recharts animation is JS-driven, not a CSS transition, so this block does not touch it. That is fine because plan **001** already disables chart animation unconditionally (`isAnimationActive={false}`). No JS `useReducedMotion` hook is needed once 001 has landed. If 001 has NOT been applied, add `isAnimationActive={false}` to the chart series as part of that plan — do not duplicate it here.

## Repo conventions to follow

- Global styles live in `app/globals.css` (Tailwind v4, `@import` + `@theme inline`). Add the media block as plain CSS in that file; do not create a new stylesheet.
- Exemplar of what NOT to over-do: keep it to the four declarations above — do not set `all: initial` or remove focus outlines.

## Steps

1. Open `app/globals.css`. Immediately after the `@import "tw-animate-css";` line (currently line 13), insert the `@media (prefers-reduced-motion: reduce)` block from **Target** verbatim.

## Boundaries

- Do NOT touch component files, tw-animate config, or the `@theme` tokens.
- Do NOT remove any existing animation classes — this is a preference-gated override only.
- Do NOT add dependencies.
- If `app/globals.css` no longer contains `@import "tw-animate-css";` (drift since c2e8746), STOP and report.

## Verification

- **Mechanical**: from `admin-ui/`, `npm run build` compiles; the CSS block is present in `app/globals.css`.
- **Feel check**: run the app. In Chrome DevTools → Rendering → "Emulate CSS prefers-reduced-motion: reduce". Open a dialog, a `<Select>`, and a dropdown: they should appear/disappear **without** the zoom/slide travel (opacity change is fine, movement gone). Confirm `animate-pulse` status pills and `animate-spin` loaders are effectively static. Turn the emulation off and confirm the normal enter/exit motion returns.
- **Done when**: with reduce-motion emulated, no element visibly *travels* (translates/scales/spins) on open/close; with it off, behavior is unchanged.
