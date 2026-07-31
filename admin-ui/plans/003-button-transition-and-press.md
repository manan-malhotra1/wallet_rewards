# 003 — Replace button `transition-all` and add press feedback

- **Status**: TODO
- **Commit**: c2e8746
- **Severity**: MEDIUM
- **Category**: Performance / Physicality & origin
- **Estimated scope**: 1 file (`components/ui/button.tsx`), one class-string edit

## Problem

The base button class uses `transition-all` and has no press (`:active`) feedback. `components/ui/button.tsx:16`:

```tsx
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md text-sm font-medium whitespace-nowrap transition-all outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
```

Two issues:
1. **`transition: all` is always a finding** (audit §5): it animates every changing property — including layout/box-shadow — off the GPU. The button only ever needs color, background, border, box-shadow (ring) and transform to transition.
2. **No press feedback.** A primary interactive control with no `:active` response feels dead. Audit §3 prescribes a subtle press: `transform: scale(0.97)` on `:active` with a short transform transition.

Buttons are the highest-frequency interactive element in the app, so this is broad-reach.

## Target

Swap `transition-all` for an explicit property list and add a subtle press scale. Final class string (only the animation-relevant tokens change — everything else stays byte-for-byte):

```tsx
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md text-sm font-medium whitespace-nowrap transition-[color,background-color,border-color,box-shadow,transform] duration-150 ease-out active:scale-[0.97] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
```

- `transition-[color,background-color,border-color,box-shadow,transform]` — only compositable/cheap properties, no `all`.
- `duration-150 ease-out` — 150ms is inside the 100–160ms button-press budget (audit §2).
- `active:scale-[0.97]` — subtle press (audit §3 keeps it 0.95–0.98).

Reduced-motion users are covered by plan **002** (the global media block collapses the transform duration to ~0), so no extra guard is needed here.

## Repo conventions to follow

- The button is a shadcn/ui `cva` variant component; edit only the base string passed to `cva(...)`, leave the `variants` object untouched.
- Tailwind arbitrary values are already used in this repo (e.g. `focus-visible:ring-[3px]`), so `active:scale-[0.97]` and `transition-[...]` match existing style.

## Steps

1. In `components/ui/button.tsx:16`, replace the single token `transition-all` with `transition-[color,background-color,border-color,box-shadow,transform] duration-150 ease-out active:scale-[0.97]`. Change nothing else in the string.

## Boundaries

- Do NOT modify the `variants` (variant/size) definitions or any other file.
- Do NOT change the ring/focus classes.
- Do NOT add dependencies.
- If the base string no longer contains `transition-all` (drift since c2e8746), STOP and report.

## Verification

- **Mechanical**: from `admin-ui/`, `npm run typecheck` (clean), `npm run lint` (no new errors), `npm run build` (compiles).
- **Feel check**: run the app. Press and hold any button — it should dip to ~97% scale and spring back on release. Hover it — the background color still transitions smoothly. In DevTools Animations panel at 10% speed, confirm nothing but color/background/transform is animating (no width/height/margin). With DevTools reduce-motion emulation on, confirm the press scale is effectively instant (via plan 002).
- **Done when**: `transition-all` no longer appears in `components/ui/button.tsx`, and buttons visibly respond to press.
