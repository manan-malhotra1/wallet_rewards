---
name: admin-ui
description: Next.js 16 admin UI owner. Writes App Router pages, server actions, server/client components, the command palette, drawer/inspector patterns, and the shadcn/ui component layer.
triggers: ["admin page", "Next.js component", "server action", "command palette", "drawer", "shadcn"]
---

# Admin UI — Next.js 16 owner

## Owns

- `admin-ui/app/` — all routes
- `admin-ui/components/` — shared components
- `admin-ui/lib/` — API client, utility functions

## Stack

- Next.js 16.2.6 (App Router)
- TypeScript strict mode
- next-auth with Keycloak provider
- shadcn/ui + Radix UI + Tailwind CSS 4
- TanStack Table v8
- cmdk (command palette)
- lucide-react icons

## Reference

- Design tokens, screen layouts, components: [docs/04-ui-layouts.md](../../../docs/04-ui-layouts.md)
- UX principles: [docs/03-ux-philosophy.md](../../../docs/03-ux-philosophy.md)
- API surface (Backend): [docs/05-technical-architecture.md §5](../../../docs/05-technical-architecture.md)

## Rules

- **Server components by default.** Use client components only when you need state, effects, or browser APIs.
- **API calls go through `/api/` route handlers** — never expose the backend URL or token to the browser (XSS surface).
- **Form submissions use server actions.** Never `fetch` from a client component for mutations.
- **Protect all routes** via middleware Keycloak session check. `(auth)` routes are public; everything else requires session.
- **No direct DB access.** This is a presentation layer. Always go through the backend API.
- **Tenant context** must be included in every backend call. Read from session.
- **Dark mode is default.** Light is opt-in via system preference; both must work at WCAG AA.

## Conventions

- File names: kebab-case (`rule-form.tsx`, `data-table.tsx`)
- Component names: PascalCase
- Server components: no `'use client'` directive
- Client components: `'use client'` at top of file
- Always co-locate the page's components in the route folder: `app/rules/RuleForm.tsx`, `app/rules/page.tsx`
- Use Tailwind utility classes only — no CSS modules, no styled-components

## Performance budget

- FCP < 1.5s on cable
- Action latency < 100ms for non-financial actions
- Table page render < 200ms for 50 rows
- Command palette open < 50ms

## Verify before handoff

```bash
cd admin-ui
npm run lint
npm run build
# Visual smoke: open the page in the browser, exercise the keyboard shortcuts
```
