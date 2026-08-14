# Glassmorphism Admin UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the admin UI to tenant-branded glassmorphism — an ambient gradient atmosphere with frosted translucent surfaces — per the approved spec `docs/superpowers/specs/2026-08-13-glassmorphism-admin-ui-design.md`.

**Architecture:** A pure `deriveGlassTokens()` in `lib/brand-palette.ts` derives per-tenant glass values (atmosphere gradients, panel/overlay tints, border, blur) for dark + light; `tenant-theme-style.tsx` emits them as CSS vars server-side (no FOUC). `globals.css` defines Ocean defaults, paints the atmosphere on `body`, and provides three `@layer components` utilities (`.glass-panel`, `.glass-overlay`, `.glass-inset`) with solid fallbacks under `@supports not (backdrop-filter…)` and `prefers-reduced-transparency`. The ~12 shared primitives + app shell apply the classes once; route files only change in one mechanical sweep (table wrappers).

**Tech Stack:** Next.js 16 App Router, Tailwind v4 (`@theme inline`, `@layer components`), shadcn/ui primitives, Vitest.

**Important theme facts (read before Task 1):**
- Light is the `:root` default; dark is the `.dark` class toggled by `next-themes` (see `@custom-variant dark` in `globals.css`). NOT `prefers-color-scheme`.
- `--destructive` and status-pill colours are never brand-derived. Do not touch them.
- Glass classes MUST be defined inside `@layer components` so Tailwind utility classes (e.g. `rounded-none`, `border-0`) can still override them.
- Backend is untouched. Mobile simulator (`mobile-simulator/`) is untouched.

---

### Task 1: `deriveGlassTokens` in the palette lib (TDD)

**Files:**
- Modify: `admin-ui/lib/brand-palette.ts` (append after `deriveTokens`, ~line 440)
- Test: `admin-ui/lib/brand-palette.test.ts` (append)

- [x] **Step 1: Write the failing tests** — append to `admin-ui/lib/brand-palette.test.ts` (add `deriveGlassTokens`, `hexToRgba` to the existing import from `./brand-palette`):

```ts
/** Pull every `rgba(..., A)` alpha out of a gradient-image string. */
function alphas(image: string): number[] {
  return [...image.matchAll(/rgba\(\d+, \d+, \d+, ([0-9.]+)\)/g)].map((m) =>
    parseFloat(m[1]),
  );
}

describe("hexToRgba", () => {
  it("converts a hex colour and alpha into an rgba() string", () => {
    expect(hexToRgba("#0C5888", 0.5)).toBe("rgba(12, 88, 136, 0.5)");
    expect(hexToRgba("#FFFFFF", 1)).toBe("rgba(255, 255, 255, 1)");
  });
});

describe("deriveGlassTokens", () => {
  it("derives gradient images, tints and blur radii for both schemes", () => {
    const g = deriveGlassTokens();
    for (const scheme of [g.dark, g.light]) {
      expect(scheme.atmosphereImage).toMatch(/^radial-gradient\(/);
      expect(scheme.atmosphereImage.match(/radial-gradient\(/g)).toHaveLength(3);
      expect(scheme.atmosphereBase).toMatch(HEX);
      expect(scheme.panel).toMatch(/^rgba\(/);
      expect(scheme.overlay).toMatch(/^rgba\(/);
      expect(scheme.border).toMatch(/^rgba\(/);
      expect(scheme.blurPanel).toBe("14px");
      expect(scheme.blurOverlay).toBe("18px");
    }
  });

  it("keeps atmosphere blob alphas within the spec bounds", () => {
    const g = deriveGlassTokens();
    // Spec §2: dark blob alphas ≤ 0.55, light blob alphas ≤ 0.25.
    for (const a of alphas(g.dark.atmosphereImage)) expect(a).toBeLessThanOrEqual(0.55);
    for (const a of alphas(g.light.atmosphereImage)) expect(a).toBeLessThanOrEqual(0.25);
  });

  it("re-tints with the tenant brand and differs between schemes", () => {
    const ocean = deriveGlassTokens();
    const berry = deriveGlassTokens("#243B8F", "#FFF0C9");
    expect(berry.dark.atmosphereImage).not.toBe(ocean.dark.atmosphereImage);
    expect(ocean.dark.atmosphereImage).not.toBe(ocean.light.atmosphereImage);
    // Dark overlay carries the brand hue (occluding, not pure white).
    expect(ocean.dark.overlay).toBe(hexToRgba(darken(DEFAULT_ACCENT, 0.55), 0.78));
  });
});
```

Also add `darken` to the test file's import list if not already imported.

- [x] **Step 2: Run tests to verify they fail**

Run: `cd admin-ui && npx vitest run lib/brand-palette.test.ts`
Expected: FAIL — `deriveGlassTokens` / `hexToRgba` are not exported.

- [x] **Step 3: Implement** — append to `admin-ui/lib/brand-palette.ts`:

```ts
/**
 * Convert a hex colour + alpha into an `rgba(r, g, b, a)` CSS string.
 *
 * @param hex - a `#RGB`/`#RRGGBB` colour
 * @param alpha - opacity in [0, 1], emitted verbatim
 * @returns an `rgba(...)` string usable in CSS values
 */
export function hexToRgba(hex: string, alpha: number): string {
  const c = hexToSrgb(hex);
  const ch = (v: number) => Math.round(clamp(v) * 255);
  return `rgba(${ch(c.r)}, ${ch(c.g)}, ${ch(c.b)}, ${alpha})`;
}

/** The glass design tokens for one colour scheme (see the glassmorphism spec). */
export interface GlassTokens {
  /** Comma-joined radial gradients — the atmosphere `background-image`. */
  atmosphereImage: string;
  /** Hex base colour painted under the gradient blobs (`background-color`). */
  atmosphereBase: string;
  /** Panel tint for in-flow surfaces (`.glass-panel`). */
  panel: string;
  /** Higher-opacity tint for floating surfaces (`.glass-overlay`). */
  overlay: string;
  /** Hairline border colour shared by all glass surfaces. */
  border: string;
  /** Backdrop blur radius for panels, e.g. `"14px"`. */
  blurPanel: string;
  /** Backdrop blur radius for overlays, e.g. `"18px"` (spec cap: 20px). */
  blurOverlay: string;
}

/** Dark + light glass token sets for a tenant. */
export interface DerivedGlass {
  light: GlassTokens;
  dark: GlassTokens;
}

/**
 * Derive the glassmorphism token set from a tenant's two brand colours
 * (spec: docs/superpowers/specs/2026-08-13-glassmorphism-admin-ui-design.md §2).
 *
 * The atmosphere is three accent-tinted radial blobs (accent, the 0.382 ramp
 * companion, a darkened deep) over a near-black (dark) / near-white (light)
 * base. Panel/overlay tints are white-frost rgba values; the dark overlay
 * carries the darkened brand hue at high alpha so floating surfaces occlude
 * what's beneath them. Blob alphas stay within the spec bounds
 * (dark ≤ 0.55, light ≤ 0.25) and blur is capped below 20px.
 *
 * @param accent - the deep brand hex colour (defaults to {@link DEFAULT_ACCENT})
 * @param light - the pale brand hex colour (defaults to {@link DEFAULT_LIGHT})
 * @returns `{ light, dark }` glass token sets
 */
export function deriveGlassTokens(
  accent: string = DEFAULT_ACCENT,
  light: string = DEFAULT_LIGHT,
): DerivedGlass {
  const mid = ramp(accent, light, 0.382);
  const deep = darken(accent, 0.25);
  const blobs = (a1: number, a2: number, a3: number) =>
    [
      `radial-gradient(ellipse 60% 50% at 15% 10%, ${hexToRgba(accent, a1)}, transparent 60%)`,
      `radial-gradient(ellipse 50% 45% at 85% 90%, ${hexToRgba(mid, a2)}, transparent 60%)`,
      `radial-gradient(ellipse 45% 40% at 70% 20%, ${hexToRgba(deep, a3)}, transparent 55%)`,
    ].join(", ");

  return {
    dark: {
      atmosphereImage: blobs(0.5, 0.28, 0.4),
      atmosphereBase: darken(accent, 0.9),
      panel: "rgba(255, 255, 255, 0.06)",
      overlay: hexToRgba(darken(accent, 0.55), 0.78),
      border: "rgba(255, 255, 255, 0.12)",
      blurPanel: "14px",
      blurOverlay: "18px",
    },
    light: {
      atmosphereImage: blobs(0.22, 0.14, 0.1),
      atmosphereBase: ramp(accent, light, 0.96),
      panel: "rgba(255, 255, 255, 0.55)",
      overlay: "rgba(255, 255, 255, 0.8)",
      border: "rgba(255, 255, 255, 0.75)",
      blurPanel: "14px",
      blurOverlay: "18px",
    },
  };
}
```

- [x] **Step 4: Run tests to verify they pass**

Run: `cd admin-ui && npx vitest run lib/brand-palette.test.ts`
Expected: PASS (all existing + new tests).

- [x] **Step 5: Commit**

```bash
git add admin-ui/lib/brand-palette.ts admin-ui/lib/brand-palette.test.ts
git commit -m "feat(admin-ui): derive per-tenant glassmorphism tokens in the palette lib"
```

---

### Task 2: Emit glass CSS vars + atmosphere + utilities

**Files:**
- Modify: `admin-ui/components/branding/tenant-theme-style.tsx`
- Modify: `admin-ui/app/globals.css` (after the `.dark` block, and the `body` rule at ~line 172)
- Modify: `admin-ui/components/app-shell/app-shell.tsx:32`

- [x] **Step 1: Print the Ocean default glass values** (they get pasted as static defaults, same convention as the existing palette defaults in `globals.css`):

Run from `admin-ui/`:
```bash
npx tsx -e "import {deriveGlassTokens} from './lib/brand-palette'; console.log(JSON.stringify(deriveGlassTokens(), null, 2))"
```
Expected: a JSON object with `light` and `dark` `GlassTokens`. Keep the output for Step 3.

- [x] **Step 2: Emit tenant glass vars in `tenant-theme-style.tsx`** — extend the existing component (it already emits `:root{…}.dark{…}`):

```tsx
import {
  deriveGlassTokens,
  deriveTokens,
  type GlassTokens,
  type TokenMap,
} from "@/lib/brand-palette";
```

Add below `toCssVars`:

```tsx
/** Serialise one scheme's glass tokens into CSS custom-property declarations. */
function toGlassVars(g: GlassTokens): string {
  return (
    `--glass-atmosphere-image:${g.atmosphereImage};` +
    `--glass-atmosphere-base:${g.atmosphereBase};` +
    `--glass-panel:${g.panel};` +
    `--glass-overlay:${g.overlay};` +
    `--glass-border:${g.border};` +
    `--glass-blur-panel:${g.blurPanel};` +
    `--glass-blur-overlay:${g.blurOverlay};`
  );
}
```

And change the derivation + `css` construction in the component body to:

```tsx
  const { light: lightTokens, dark: darkTokens } = deriveTokens(accent, light);
  const glass = deriveGlassTokens(accent, light);
  const css =
    `:root{${toCssVars(lightTokens)}${toGlassVars(glass.light)}}` +
    `.dark{${toCssVars(darkTokens)}${toGlassVars(glass.dark)}}`;
```

- [x] **Step 3: Add Ocean defaults + atmosphere + glass utilities to `globals.css`.**

(a) Append the printed Step-1 values inside the existing `:root` block (light values) and `.dark` block (dark values), after the `--sidebar-ring` line in each, as:

```css
  /* Glassmorphism (spec 2026-08-13) — Ocean defaults; overridden per tenant
     by TenantThemeStyle exactly like the palette tokens above. */
  --glass-atmosphere-image: <atmosphereImage from Step 1 for this scheme>;
  --glass-atmosphere-base: <atmosphereBase>;
  --glass-panel: <panel>;
  --glass-overlay: <overlay>;
  --glass-border: <border>;
  --glass-blur-panel: 14px;
  --glass-blur-overlay: 18px;
```

(b) Replace the existing `body` rule with:

```css
body {
  /* Glass atmosphere: tenant-tinted radial blobs over a base colour. The
     fallback blocks below strip the image and restore --background. */
  background-color: var(--glass-atmosphere-base);
  background-image: var(--glass-atmosphere-image);
  background-attachment: fixed;
  color: var(--foreground);
  font-family: var(--font-sans);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
```

(c) Append at the end of the file:

```css
/* ---------------------------------------------------------------------------
 * Glassmorphism surfaces (spec: docs/superpowers/specs/2026-08-13-…-design.md)
 * Inside @layer components so Tailwind utilities (rounded-none, border-0…)
 * can still override individual properties.
 * ------------------------------------------------------------------------- */
@layer components {
  /* In-flow surfaces: cards, table containers, sidebar, page headers. */
  .glass-panel {
    background-color: var(--glass-panel);
    border: 1px solid var(--glass-border);
    -webkit-backdrop-filter: blur(var(--glass-blur-panel));
    backdrop-filter: blur(var(--glass-blur-panel));
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.08),
      0 6px 22px rgba(0, 0, 0, 0.25);
  }
  /* Floating layer: dialogs, drawers, popovers, dropdowns, toasts, tooltips.
     Higher opacity + stronger blur/shadow so content beneath never bleeds
     through text. */
  .glass-overlay {
    background-color: var(--glass-overlay);
    border: 1px solid var(--glass-border);
    -webkit-backdrop-filter: blur(var(--glass-blur-overlay));
    backdrop-filter: blur(var(--glass-blur-overlay));
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.08),
      0 16px 48px rgba(0, 0, 0, 0.45);
  }
  /* Nested regions INSIDE a glass panel: tint only, no blur — blur inside
     blur produces the double-blur artifact. */
  .glass-inset {
    background-color: var(--glass-panel);
    border: 1px solid var(--glass-border);
  }
}

/* Fallback 1: engines without backdrop-filter, and Fallback 2: reduced-
   transparency users — both defined below as CSS-variable swaps, not
   per-class recipe restatements (see globals.css for the as-implemented
   version — it is the source of truth, not this plan). */
```

> **As-implemented note (fix round, 2026-08-13):** the two fallback blocks
> above were reworked from per-class rules into pure `:root`/`.dark`
> variable swaps (redefining `--glass-*` back to the solid design tokens,
> with blur collapsed to `0px`), so `.glass-panel`/`.glass-overlay`/
> `.glass-inset` never have their recipe restated outside `@layer
> components` and can't drift from it. Three details the original snippet
> above doesn't capture — see `admin-ui/app/globals.css` for the exact,
> current CSS:
> - The universal `* { border-color: var(--border) }` reset is wrapped in
>   `@layer base { ... }`, because an unlayered version beats `@layer
>   components` regardless of source order and made `--glass-border` inert.
> - `.glass-panel`/`.glass-overlay` shadows are tokenised as
>   `--glass-shadow-panel`/`--glass-shadow-overlay` (also swapped by the
>   fallbacks) instead of literal `box-shadow` values, so the fallback can
>   restore a flatter elevation without repeating the glass recipe.
> - Both fallback blocks use the selector `:root:root` (specificity 0,2,0),
>   not `:root, .dark` — `TenantThemeStyle` emits an unlayered `:root{…}`
>   later in the document, and a plain `:root` here ties on specificity and
>   loses, silently reinstating glass for every branded tenant. The
>   reduced-transparency block additionally sets `.glass-panel`/
>   `.glass-overlay`'s `backdrop-filter`/`-webkit-backdrop-filter` to `none`
>   explicitly, since `blur(0px)` is visually a no-op but still opens a
>   stacking/backdrop context.

- [x] **Step 4: Let the atmosphere show through the shell** — `admin-ui/components/app-shell/app-shell.tsx:32`, change:

```
"flex h-screen w-screen overflow-hidden bg-background text-foreground"
```
to
```
"flex h-screen w-screen overflow-hidden bg-transparent text-foreground"
```

- [x] **Step 5: Verify**

Run: `cd admin-ui && npx tsc --noEmit && npx vitest run lib/ && npm run lint`
Expected: all clean. Then load `http://localhost:3000` on the dev server: the page background shows the Ocean gradient blobs; surfaces still look solid (classes not applied yet) — that's expected at this task boundary.

- [x] **Step 6: Commit**

```bash
git add admin-ui/components/branding/tenant-theme-style.tsx admin-ui/app/globals.css admin-ui/components/app-shell/app-shell.tsx
git commit -m "feat(admin-ui): glass CSS vars, atmosphere background, glass utilities + fallbacks"
```

---

### Task 3: Apply glass classes to the shared primitives + shell

**Files (exact class-string edits; each line shows old → new for the FIRST string argument of `cn(...)` at that location):**

- [x] **Step 1: Primitives.** Make these replacements (keep everything else in each string unchanged; listed fragments are removed/added exactly):

1. `admin-ui/components/ui/card.tsx:14` — remove `bg-card`, `border`, `shadow-sm`; prepend `glass-panel`:
   `"glass-panel text-card-foreground flex flex-col gap-6 rounded-xl py-6"`
2. `admin-ui/components/ui/kpi-card.tsx:50` — remove `border`, `bg-card`, `shadow-sm`; prepend `glass-panel`:
   `"glass-panel rounded-lg p-5 transition-shadow hover:shadow-md"`
3. `admin-ui/components/ui/dialog.tsx:46` — remove `bg-card`, `border`, `shadow-2xl`; prepend `glass-overlay` (leave the explanatory comment above it, updating `bg-card` → `glass-overlay` in its wording):
   `"glass-overlay text-card-foreground data-[state=open]:animate-in … rounded-lg p-6 duration-200 sm:max-w-lg"` (all other fragments unchanged)
4. `admin-ui/components/ui/drawer.tsx:42` — remove `bg-card`, `border-l`, `shadow-2xl`; prepend `glass-overlay`:
   `"glass-overlay text-card-foreground fixed right-0 top-0 z-50 flex h-full w-full max-w-[480px] flex-col"`
5. `admin-ui/components/ui/dialog.tsx:26` — scrim: `bg-black/70` → `bg-black/40` (glass invariant documented above `.glass-overlay` in globals.css — a near-opaque scrim turns the glass into a flat slab with nothing to refract; the atmosphere needs to read through).
6. `admin-ui/components/ui/drawer.tsx:25` — scrim: `bg-black/60` → `bg-black/40` (same invariant).
7. `admin-ui/components/ui/select.tsx:46` — remove `bg-popover`, `border`, `shadow-md`; prepend `glass-overlay`:
   `"glass-overlay text-popover-foreground data-[state=open]:animate-in … rounded-md"` (rest unchanged)
8. `admin-ui/components/ui/tooltip.tsx:25` — remove `border`, `border-border`, `bg-popover`, `shadow-md`; prepend `glass-overlay`:
   `"glass-overlay z-50 max-w-sm rounded-md px-3 py-2 text-xs text-popover-foreground"`
9. `admin-ui/components/ui/toast.tsx:36` — replace `group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg` with `glass-overlay group-[.toaster]:text-foreground`:
   `"group toast glass-overlay group-[.toaster]:text-foreground"`

- [x] **Step 2: App shell.**

10. `admin-ui/components/app-shell/sidebar.tsx:232` — remove `border-r border-sidebar-border bg-sidebar`; prepend `glass-panel rounded-none border-0 border-r`:
    `"glass-panel rounded-none border-0 border-r flex h-full w-[240px] shrink-0 flex-col"`
11. `admin-ui/components/app-shell/topbar.tsx:68` — remove `bg-background`; prepend `glass-panel rounded-none border-0 border-b`:
    `"glass-panel rounded-none border-0 border-b flex h-14 shrink-0 items-center gap-3 px-4"`
12. `admin-ui/components/ui/page-header.tsx:17` — remove `border-b bg-background`; prepend `glass-panel rounded-none border-0 border-b`:
    `"glass-panel rounded-none border-0 border-b flex flex-wrap items-end justify-between gap-4 px-6 py-5"`
13. `admin-ui/components/app-shell/tenant-switcher.tsx:55` — remove `border bg-popover shadow-md`; prepend `glass-overlay`:
    `"glass-overlay z-50 w-[260px] rounded-md p-1 text-popover-foreground"`
14. `admin-ui/components/app-shell/user-menu.tsx:38` — remove `border bg-popover shadow-md`; prepend `glass-overlay`:
    `"glass-overlay z-50 w-[240px] rounded-md p-1 text-popover-foreground"`

The command palette needs no edit — it renders through `DialogContent` (already glass via edit 3).

- [x] **Step 3: Run the full UI test suite** (asserts roles/labels, not colours — must stay green):

Run: `cd admin-ui && npm test`
Expected: all files pass (345+ tests). If any test fails on a class assertion, fix the TEST only if it asserted a removed cosmetic class; behaviour assertions must not change.

- [x] **Step 4: Visual smoke on the dev server** — dashboard renders frosted cards/sidebar over the atmosphere; open one dialog and one dropdown (both frosted, text fully legible).

- [x] **Step 5: Commit**

```bash
git add admin-ui/components/ui/card.tsx admin-ui/components/ui/kpi-card.tsx admin-ui/components/ui/dialog.tsx admin-ui/components/ui/drawer.tsx admin-ui/components/ui/select.tsx admin-ui/components/ui/tooltip.tsx admin-ui/components/ui/toast.tsx admin-ui/components/app-shell/sidebar.tsx admin-ui/components/app-shell/topbar.tsx admin-ui/components/ui/page-header.tsx admin-ui/components/app-shell/tenant-switcher.tsx admin-ui/components/app-shell/user-menu.tsx
git commit -m "feat(admin-ui): frost the shared primitives and app shell (glass-panel/glass-overlay)"
```

---

### Task 4: Table-wrapper sweep + login page

Route pages wrap tables in a repeated recipe (`overflow-hidden rounded-lg border … bg-[--color-surface-1]` or `bg-card`). One mechanical sweep converts them to glass panels.

**Files:**
- Modify: every file listed by the grep in Step 1
- Modify: `admin-ui/app/login/page.tsx:27`

- [x] **Step 1: Find the wrappers**

Run from `admin-ui/`:
```bash
grep -rn "rounded-lg border.*bg-\[--color-surface-1\]\|rounded-lg border bg-card\|rounded-xl border bg-card" app/ | grep -v node_modules
```
Expected: a list of route-level wrapper `<div>`s (campaigns, segments, users, approvals, etc.).

- [x] **Step 2: Convert each hit.** In each matched class string: remove `border` and the `bg-[--color-surface-1]` / `bg-card` fragment, prepend `glass-panel`. Example (campaigns):

Before: `"overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface-1]"`
After: `"glass-panel overflow-hidden rounded-lg"`

Do NOT touch: inputs, buttons, badges, status pills, `bg-muted` row tints, or anything inside `mobile-simulator/`.

- [x] **Step 3: Login card** — `admin-ui/app/login/page.tsx:27`, remove `border bg-card shadow-xl`, prepend `glass-panel`:
   `"glass-panel w-full max-w-md rounded-2xl p-8"`

- [x] **Step 4: Gates**

Run: `cd admin-ui && npm test && npx tsc --noEmit && npm run lint`
Expected: all clean.

- [x] **Step 5: Commit**

```bash
git add -u admin-ui/app
git commit -m "feat(admin-ui): glass table containers and login card"
```

(`git add -u` scoped to `admin-ui/app` is acceptable here because the sweep touches many route files and creates none; verify with `git status` that only intended files are staged.)

---

### Task 5: Full verification + docs

**Files:**
- Modify: `docs/design/09-admin-ui.md` (branding/theming section)

- [x] **Step 1: Full gates**

Run: `cd admin-ui && npm test && npx tsc --noEmit && npm run lint && npm run build`
Expected: tests green, no type errors, no lint errors, production build succeeds.

- [ ] **Step 2: Visual walk-through on the dev server** (`scripts/dev.sh start admin-ui` if not running). Check in **dark** then **light** (theme toggle in the user menu):
  - dashboard (KPI cards frosted, atmosphere visible behind)
  - campaigns list + create-campaign wizard dialog (text crisp on glass; nested budget section not double-blurred)
  - segments page + criteria builder dialog
  - approvals page tables
  - a dropdown (Select), the ⌘K command palette, a toast, a tooltip
  - login page (log out or open an incognito window)

- [ ] **Step 3: Custom-brand tenant check** — in the admin UI, set a tenant's brand to accent `#243B8F` / light `#FFF0C9` via the tenants page branding dialog, switch to that tenant, and confirm the atmosphere + panels re-tint away from Ocean. Reset the brand afterwards.

- [x] **Step 4: Update `docs/design/09-admin-ui.md`** — in the theming/branding section (~line 210), after the existing defaults sentence, add:

```markdown
**Glassmorphism (2026-08-13):** the UI renders as frosted translucent surfaces
over a tenant-branded atmosphere. `deriveGlassTokens()` (same lib) derives the
gradient/tint/blur set per tenant; `TenantThemeStyle` emits them as
`--glass-*` vars, and three `@layer components` utilities in `globals.css`
(`glass-panel`, `glass-overlay`, `glass-inset`) apply them via the shared
primitives. Unsupported engines and `prefers-reduced-transparency` collapse to
the previous solid surfaces. Spec:
`docs/superpowers/specs/2026-08-13-glassmorphism-admin-ui-design.md`.
```

- [x] **Step 5: Commit**

```bash
git add docs/design/09-admin-ui.md
git commit -m "docs(design): document the glassmorphism surface system"
```

---

## Self-review notes (already applied)

- Spec §2 token names match Task 2 emission and Task 1 interface exactly (`--glass-atmosphere-image/base`, `--glass-panel`, `--glass-overlay`, `--glass-border`, `--glass-blur-panel/overlay`).
- Spec's "popover/dropdown" surfaces map to `select.tsx`, `tenant-switcher.tsx`, `user-menu.tsx`, `tooltip.tsx` — this repo has no `popover.tsx`/`dropdown-menu.tsx` primitives.
- Dialog/drawer scrims already use `bg-black/60–70 backdrop-blur-sm` — intentionally untouched.
- `input.tsx`/`textarea.tsx`/`checkbox.tsx` keep solid `bg-background` on purpose (readability inside glass dialogs; spec §4).
- The user's protected working-tree files (`branding-dialog.tsx`, `create-tenant-dialog.tsx`, `brand-palette.ts` etc.) were all COMMITTED in `c2c92b9`; `globals.css` and `brand-palette.ts` are safe to modify now. `admin-ui/next-env.d.ts` remains uncommitted generated noise — never stage it.
