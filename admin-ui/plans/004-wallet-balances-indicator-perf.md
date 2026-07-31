# 004 — Animate the wallet-balance indicator on the GPU, not `width`

- **Status**: DONE (ade59cb)
- **Commit**: c2e8746
- **Severity**: MEDIUM
- **Category**: Performance
- **Estimated scope**: 1 file (`app/(authenticated)/users/_components/wallet-balances.tsx`)

## Problem

The wallet carousel's page-indicator dots use `transition-all` on a class set that changes `width` (`w-1.5` ↔ `w-4`). `app/(authenticated)/users/_components/wallet-balances.tsx:65`:

```tsx
<button
  key={w.id}
  type="button"
  aria-label={`Show ${w.currency} wallet`}
  onClick={() => goTo(i)}
  className={`h-1.5 rounded-full transition-all ${
    i === active ? "w-4 bg-foreground" : "w-1.5 bg-muted-foreground/40"
  }`}
/>
```

Two audit §5 problems in one line: `transition-all`, and it animates **`width`** — a layout property that triggers reflow + paint + composite on every frame, off the GPU. The active-dot "grow" should ride on `transform`.

## Target

Keep the visual (a short pill that widens when active) but drive it with `transform: scaleX()` from the left edge, and transition only `transform` + `background-color`. Give every dot a fixed base width and scale the active one horizontally.

```tsx
<button
  key={w.id}
  type="button"
  aria-label={`Show ${w.currency} wallet`}
  onClick={() => goTo(i)}
  style={{ transformOrigin: "left" }}
  className={`h-1.5 w-4 origin-left rounded-full transition-[transform,background-color] duration-200 ease-out ${
    i === active ? "scale-x-100 bg-foreground" : "scale-x-[0.375] bg-muted-foreground/40"
  }`}
/>
```

- Base width `w-4` (1rem); inactive scales to `0.375` → `0.375 × 1rem = 0.375rem`, matching the old `w-1.5` (0.375rem) exactly. Active is full `w-4`.
- `origin-left` (Tailwind) so the pill grows/shrinks from its left edge, not the center — keeps the row's left alignment stable. The inline `transformOrigin` is redundant with `origin-left`; keep only the `origin-left` class and drop the `style` prop if you prefer — either is fine, but do not omit both.
- `transition-[transform,background-color] duration-200 ease-out` — GPU-friendly, 200ms, strong-ish ease.

Reduced-motion is covered globally by plan **002**.

## Repo conventions to follow

- This is a client component using template-literal className with a ternary for active state — preserve that structure, only swap the animated properties and the active/inactive tokens.
- Tailwind arbitrary values (`scale-x-[0.375]`) are already used across the repo.

## Steps

1. In `wallet-balances.tsx:65`, replace the `transition-all` + `w-4`/`w-1.5` width toggle with the `w-4 origin-left ... transition-[transform,background-color] duration-200 ease-out` + `scale-x-100`/`scale-x-[0.375]` version from **Target**. Keep `key`, `type`, `aria-label`, `onClick` unchanged.

## Boundaries

- Do NOT change the carousel logic (`goTo`, `active`, `wallets`) or any other markup.
- Do NOT touch other files.
- Do NOT add dependencies.
- If line 65's class no longer toggles `w-4`/`w-1.5` (drift since c2e8746), STOP and report.

## Verification

- **Mechanical**: from `admin-ui/`, `npm run typecheck` (clean), `npm run build` (compiles).
- **Feel check**: open a user with 2+ wallets (`/users` → a user detail with the wallet carousel). Click between dots: the active dot widens smoothly and the others shrink, growing from the left edge with no horizontal jump of the row. In DevTools Performance/Animations, confirm the transition is `transform` (composited), not `width`. Verify the inactive dot width visually matches the previous build (no size regression).
- **Done when**: `transition-all` is gone from `wallet-balances.tsx`, and the indicator animates via `scale-x` transform.
