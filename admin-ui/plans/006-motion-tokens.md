# 006 — Introduce shared motion tokens (easing + duration scale)

- **Status**: TODO
- **Commit**: c2e8746
- **Severity**: LOW
- **Category**: Cohesion & tokens
- **Estimated scope**: 1 file (`app/globals.css`); optional adoption in later plans

## Problem

There are no shared motion tokens. Deliberate transitions rely on Tailwind's built-in `ease` (`cubic-bezier(0.4, 0, 0.2, 1)`), which is intentionally weak for UI travel, and durations are hand-typed per component (`duration-150`, `duration-200`) or left implicit. The audit calls for curves and durations to live as shared tokens so components extend one scale instead of scattering near-identical values.

`app/globals.css` currently defines only **color** tokens in its `@theme inline { … }` block — no `--ease-*` or `--duration-*`.

This is LOW severity: color/hover transitions correctly use `ease` (audit §2), so nothing is broken today. This plan is consolidation — it gives plans 003/004/005 (and future motion) a single source of truth.

## Target

Add motion tokens to `app/globals.css`. In Tailwind v4, values placed in `@theme` become utilities; to keep it simple and framework-agnostic, define plain custom properties in the `:root`/`@theme` layer and reference them via `[transition-timing-function:var(--ease-out)]` or in component `style`/CSS.

Add inside the existing `@theme inline { … }` block (alongside the color tokens):

```css
  /* Motion — strong curves for deliberate UI travel (audit §2). */
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);        /* entering/exiting UI */
  --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);    /* on-screen morphs */
  --ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);     /* iOS-like drawer */

  /* Duration scale — UI stays under 300ms (audit §2). */
  --duration-press: 150ms;    /* button/tile press */
  --duration-pop: 200ms;      /* tooltips, small popovers, dropdowns */
  --duration-panel: 300ms;    /* larger panels */
```

These are exact values from the audit catalog — do not approximate.

Adoption is intentionally out of scope for this plan beyond making the tokens available: existing `transition-colors`/`duration-150` usages keep working. Later motion work (and plans 003/004/005 if not yet applied) may reference `var(--ease-out)` etc. instead of literals, but this plan only *defines* the tokens.

## Repo conventions to follow

- Tokens live in `app/globals.css` inside `@theme inline { … }` (that is where all `--color-*` tokens are). Add the motion tokens in the same block, grouped under a comment.
- Naming mirrors the existing `--color-*` / `--radius` style: lowercase, hyphenated, semantic.

## Steps

1. Open `app/globals.css`, locate the `@theme inline {` block.
2. Add the six motion tokens from **Target** inside that block (a comment-grouped section is fine). Change no existing token.

## Boundaries

- Do NOT refactor existing components to use the tokens in this plan (separate, deliberate work).
- Do NOT rename or alter color tokens.
- Do NOT add dependencies or new stylesheets.
- If `app/globals.css` has no `@theme inline {` block (drift since c2e8746), STOP and report.

## Verification

- **Mechanical**: from `admin-ui/`, `npm run build` compiles; `grep -c "\-\-ease-out" app/globals.css` returns ≥1.
- **Feel check**: none required (definition-only). Optional sanity: in DevTools, inspect `:root`/`html` computed styles and confirm `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)` resolves.
- **Done when**: the motion tokens exist in `app/globals.css` and the build is green.
