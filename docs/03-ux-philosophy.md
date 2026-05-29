# UX Philosophy & Design System

> **Document type:** UX Guidelines
> **Version:** 0.1
> **Date:** 2026-05-28
> **Scope:** Admin UI (mobile deferred to Phase 2)

For concrete screen-by-screen wireframes, see [04-ui-layouts.md](04-ui-layouts.md). This document captures the *why* behind every UI decision.

---

## 1. UX principles

Five principles that bind every design choice.

### 1.1 Density over decoration
Operators spend hours in this tool. They scan, they don't browse. Default to tables over cards. Use whitespace strategically, not habitually. A row should show the operator everything they need to decide if they want to click into the detail — status, amount, age, identifier, action affordance.

### 1.2 Keyboard is faster than mouse
Every action reachable by mouse must also be reachable by keyboard. The command palette (⌘K) is the *primary* navigation — sidebar exists as a fallback for discovery, not the default route. J/K to traverse rows. ⌘↵ to confirm. ESC to dismiss. Every modal that supports keyboard escape must dismiss on ESC.

### 1.3 Drawer over navigation
Don't navigate away when the operator wants to look at one row's detail. Open a drawer (slide-over) or use a persistent inspector pane. The list stays visible; URL updates so the view is shareable. Navigation is reserved for switching task, not for inspecting one item within a task.

### 1.4 Status is always visible
Every transaction, redemption, segment, rule, sweep entry has a state. The operator should never have to guess. Coloured dot + label in tables; full pill + secondary metadata in detail views. The MANUAL_REVIEW state in particular must be high-contrast — it represents work that requires human action.

### 1.5 Zero ambiguity on financial actions
For ledger writes (reversal, manual resolution, force-status-check), we do not use optimistic UI. Show the action as pending until the server confirms. Show the resulting ledger entry on completion. Never let the operator wonder "did it work?" The financial audit trail must always be visible from any state-changing action.

---

## 2. Design system foundation

| Token | Value | Rationale |
|---|---|---|
| Component library | shadcn/ui + Radix primitives | Headless, accessible, themeable |
| CSS approach | Tailwind CSS (4.x) | Utility-first, co-located styles |
| Typography | Geist Sans (UI), Geist Mono (IDs / amounts) | High readability at small sizes, strong tabular-nums |
| Color space | oklch | Perceptually uniform — status colours feel consistent |
| Dark mode | **Default**, light opt-in via system preference | Linear/Stripe convention, easier on long sessions |
| Icon library | lucide-react | Consistent stroke weight, tree-shakeable |
| Tables | TanStack Table v8 | Headless, supports sort/filter/multi-select |
| Command palette | cmdk | Battle-tested by Linear, Vercel |

### Semantic color roles

| Role | Used for |
|---|---|
| `--brand` | Primary buttons, selected nav |
| `--accent` | Highlights, links, info pills |
| `--surface-0/1/2/3` | Page bg, card, hover, selected |
| `--border` | Dividers, input outlines |
| `--text-1/2/3` | Primary, secondary, muted |
| `--success` | COMPLETED, healthy KPIs, green dots |
| `--warning` | PENDING, MANUAL_REVIEW, amber pulses |
| `--danger` | FAILED, REVERSED, destructive actions |
| `--credit` | Money / points coming IN (green) |
| `--debit` | Money / points going OUT (red) |
| `--points` | Points-specific colour (amber) |

(Exact oklch values in [04-ui-layouts.md §2.1](04-ui-layouts.md#21-colour-scale-oklch).)

---

## 3. Component conventions

### Money and Points
- Always tabular-nums (`font-variant-numeric: tabular-nums`) so columns align.
- Currency code is colocated and small: `R 1,284.50 ZAR`.
- Points use the points colour and `pts` suffix: `4,800 pts`.
- Credit/debit colour applied only in transactional contexts (balance views show neutral colour).
- Decimals stored as `NUMERIC(20, 6)` in DB; UI rounds for display but exposes full value on hover.

### Status pills
- Compact (dot only) in dense tables.
- Full (dot + label) in detail views.
- PENDING dot animates (subtle pulse) — it's an actionable state.
- MANUAL_REVIEW uses `--danger` colour, not `--warning`, because it requires human action.

### Forms
- Labels above inputs (not floating, not inline placeholders-as-labels).
- Required fields marked with `*` after label.
- Inline validation on blur, not on every keystroke.
- Live summary sentence on complex forms (rules builder) regenerates as fields change.
- Destructive actions require a confirm dialog with a typed-confirmation pattern (e.g. type `SUSPEND` to confirm).

### Tables
- Sortable column headers click to toggle sort.
- Default sort: most-relevant-recent first (e.g. transactions by `created_at DESC`).
- Multi-select with shift-click for ranges.
- Bulk-action toolbar appears above table when ≥1 row selected.
- Pagination at 50 rows per page; "Load more" pattern for activity feeds.

### Audit hint
Wherever an action triggers an audit log entry (NFR-0250), include a small `⊕ audit-logged` hint near the action button so operators know what'll be recorded.

---

## 4. Empty / loading / error states

**Empty (first time)** — illustration + explanation + clear next action.
**Empty (filtered)** — message + "clear filters" button.
**Loading** — skeleton rows for tables; spinners only on action buttons during submit.
**Error (data fetch)** — inline banner with retry; never crash the table.
**Error (action)** — toast with full error code; if recoverable, retry button.

---

## 5. Accessibility

- All interactive elements keyboard-navigable (Tab order logical).
- All icons either `aria-label`-ed or `aria-hidden="true"` if decorative.
- Color is never the *only* signal — always pair with text or icon (e.g. status pills have dot + label, not just colour).
- Contrast: 4.5:1 minimum for normal text, 3:1 for large text (WCAG AA).
- Screen reader tested with VoiceOver before each release.
- All modals/drawers trap focus and restore focus on close.

---

## 6. Performance budget

- Page load (FCP): < 1.5s on cable connection
- Action latency (visible feedback): < 100ms
- Table page render: < 200ms for 50 rows
- Command palette open: < 50ms

If a server action will exceed 100ms, show optimistic UI immediately (or a loading state if the action is financial).
