# Glassmorphism Admin UI — Design

**Date:** 2026-08-13
**Status:** Approved (brainstorm with visual companion; user chose glass
surfaces / tenant-branded atmosphere / light-mode glass / token+primitive
implementation)
**Scope:** `admin-ui/` only. No backend changes. Mobile simulator untouched.

## 1. Goal

Restyle the web admin UI to a glassmorphism design: an ambient,
tenant-branded gradient atmosphere behind the app, with every surface
(sidebar, cards, tables, dialogs, popovers) rendered as a translucent
frosted panel over it. Dark and light schemes both get the treatment.
Today's flat look remains as the automatic fallback where glass can't
render (`backdrop-filter` unsupported, `prefers-reduced-transparency`).

Decisions taken during brainstorm (each shown as a visual mockup):

| Question | Decision |
|---|---|
| Glass intensity | **B — glass surfaces** (not accents-only, not neon/maximal) |
| Atmosphere colour | **Tenant-branded** — derived from the active tenant's brand anchors |
| Light mode | **Light glass too** — same system, white-frost recipe |
| Implementation | **Token + primitive restyle** (central, not page-by-page) |

## 2. Glass tokens (per-tenant derivation)

`admin-ui/lib/brand-palette.ts` gains a pure `glassTokens(accent, light)`
function alongside the existing `brandScale()`. From the two brand anchor
hexes it derives, for **dark** and **light** schemes:

- **Atmosphere**: three radial-gradient stops — two accent-tinted blobs
  (accent + a hue-shifted companion from the existing OKLab ramp) over a
  near-black (`~#0a0f16`) / near-white (`~#eef3f7`) base. Blob alphas
  bounded: dark ≤ 0.55, light ≤ 0.25.
- **Panel tint**: `rgba` — dark: white at ~5–7% alpha; light: white at
  ~50–60% alpha.
- **Overlay tint**: same hue, higher alpha (dark ~55%, light ~75%) so
  floating surfaces occlude what's beneath them.
- **Border alpha**: hairline `rgba(255,255,255, …)` — dark ~0.12,
  light ~0.75.
- **Blur radii**: panel ~14px, overlay ~18px (hard cap 20px).

Emission: `components/branding/tenant-theme-style.tsx` adds the new vars
(`--glass-atmosphere-1..3`, `--glass-panel`, `--glass-overlay`,
`--glass-border`, `--glass-blur-panel`, `--glass-blur-overlay`) to the
inline `<style>` it already renders server-side for `:root` + `.dark` —
same no-FOUC path as the existing theme tokens. Defaults (no tenant brand)
derive from `DEFAULT_ACCENT`/`DEFAULT_LIGHT` (Ocean `#0C5888` / white).
`--destructive` and all status colours stay constant across tenants, as
today.

## 3. Surface system

`admin-ui/app/globals.css` gains the atmosphere + three utilities:

- **Atmosphere**: the layout root paints
  `background: var(--glass-atmosphere-…)` as a fixed (non-scrolling)
  backdrop.
- **`.glass-panel`** — in-flow surfaces: sidebar, stat/config cards, table
  containers, page headers. Recipe: panel tint + `backdrop-filter:
  blur(var(--glass-blur-panel))` + 1px `--glass-border` border + inset top
  highlight (`inset 0 1px 0 rgba(255,255,255,.08)`) + soft drop shadow.
- **`.glass-overlay`** — floating layer: Dialog, Drawer, Popover,
  DropdownMenu, Select content, CommandPalette, Toast, Tooltip. Same
  recipe with overlay tint, overlay blur, stronger shadow.
- **`.glass-inset`** — nested regions inside a panel (e.g. the inline
  budget section in the campaign wizard): tint + border only, **no
  backdrop-filter** — nesting blur inside blur produces the double-blur
  artifact.

Application point: the ~10 shared primitives in `admin-ui/components/ui/`
(card, table, dialog, drawer, popover, dropdown-menu, select, command
palette, toast, tooltip) plus the sidebar/layout shell in
`app/(authenticated)/layout.tsx` and the login screen. Route files do not
change; new pages inherit glass by using the primitives.

## 4. Readability, accessibility, performance

- **Text contrast** targets WCAG AA against the *worst-case* atmosphere
  stop behind a panel (accent blob at max alpha), not the average.
- **Dense data**: tables and dialog bodies sit on the higher-opacity
  overlay/panel recipes; amounts keep `tabular-nums font-mono`; row
  hover/selection states get solid-enough tints to stay scannable.
- **Fallback = today's UI**: both
  `@supports not (backdrop-filter: blur(1px))` and
  `@media (prefers-reduced-transparency: reduce)` collapse all three
  glass classes to the current solid surface colours and hide the
  atmosphere. No JS involved.
- **Performance**: blur only on panels/overlays (bounded count per view),
  never on per-row elements; blur radius capped at 20px; the atmosphere is
  a static gradient (no animation), so scrolling cost stays flat even on
  500-row tables.
- Focus rings, status pills, and `aria-*` semantics are untouched.

## 5. Scope & verification

- **In scope**: every `(authenticated)` route + the login page.
- **Out of scope**: mobile simulator, mobile app, docs, emails.
- **No behaviour change** ⇒ no new interaction tests. Gates:
  - all existing admin-ui tests stay green (they assert roles/labels, not
    colours);
  - `brand-palette.test.ts` extends to cover `glassTokens` (pure
    derivation: alpha bounds respected, dark/light variants differ, Ocean
    defaults stable);
  - `tsc`, eslint, `next build` clean;
  - visual walk-through on the dev server: dashboard, campaigns (+create
    wizard), segments, approvals, a dialog, dropdowns, command palette —
    dark and light — plus one tenant with a non-Ocean custom brand to
    prove the atmosphere re-tints.

## 6. Non-goals

- No neon/glow treatment (option C was explicitly rejected).
- No animated/parallax atmosphere.
- No per-page bespoke glass tuning — pages consume the system.
- No changes to `--destructive`/status colour semantics.
