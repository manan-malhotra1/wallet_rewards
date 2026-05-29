---
name: scaffold-ui
description: Generate a new Next.js page or component pair (server component + client component) plus server action and API client function.
---

# /scaffold-ui

## Inputs

- Route or component name
- Data fetched + actions exposed

## Outputs

For a new route `/foo`:
- `admin-ui/app/foo/page.tsx` — server component, fetches data
- `admin-ui/app/foo/FooView.tsx` — client component if needed for interactivity
- `admin-ui/app/foo/actions.ts` — server actions for mutations
- `admin-ui/lib/api/foo.ts` — typed backend API client functions
- `admin-ui/lib/schemas/foo.ts` — zod schemas (reused for client validation + server action validation)

For a reusable component:
- `admin-ui/components/{ComponentName}.tsx` with one-line JSDoc explaining the use case

## Defaults

- Server component by default. Add `'use client'` only when state/effects/handlers are needed.
- API calls server-side via the typed client — never expose `BACKEND_URL` to the browser.
- Form submissions use server actions.
- Tabular nums (`font-mono tabular-nums`) for any numeric column.
- `<StatusPill>` for any status column.
- `<Money>` / `<Points>` for amounts.
- Loading state: skeleton; never spinner for tables.

## Verify

```bash
cd admin-ui
npm run lint
npm run build
# Visual: open in browser, exercise the keyboard shortcuts
```
