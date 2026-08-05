---
paths:
  - "admin-ui/**/*.ts"
  - "admin-ui/**/*.tsx"
---

# Admin UI conventions (Next.js 16)

## Server vs client components

- **Default to server components.** They run on the server, no JS shipped, can fetch data directly.
- **`'use client'` only when you need:** state, effects, browser APIs, event handlers tied to user input.
- A client component can import server components, but server components cannot import client components for interactive use. Use the props pattern.

## Data fetching

- In server components: directly call the API via the typed client in `lib/api-endpoints.ts` (wrapping `lib/api.ts`). The Bearer token is read server-side from the Keycloak session.
- In client components: use server actions. Never `fetch` the backend directly from the browser.
- Never expose `BACKEND_URL` or `KEYCLOAK_CLIENT_SECRET` to the client. They are server-only env vars.

## Forms

- Server actions (in each route's `_actions.ts`) for submissions. Use React 19 `useActionState` (+ `useFormStatus`) for pending/error states.
- Validation: zod where it earns its keep; validate again inside the server action. Inline field validation, not on every keystroke.
- Destructive actions: confirm dialog with typed-confirmation pattern (type `SUSPEND` to confirm).

## Styling

- Tailwind utility classes only. No CSS modules, no styled-components.
- Tokens from `tailwind.config.ts` (extends the oklch palette in `docs/04-ui-layouts.md`).
- Dark mode default; light is `@media (prefers-color-scheme: light)`.
- Tabular nums for all amounts: `tabular-nums font-mono`.

## Components

- Naming: `PascalCase.tsx` for components, `kebab-case.tsx` for routes.
- Co-locate route-specific components in the route folder.
- Reusable components in `components/`. Tag with one-line JSDoc explaining the use case.
- `<Money>` and `<Points>` for all financial values — never raw numbers.
- `<StatusPill>` for every state. Never use raw text for a status field.

## Tables

- Hand-rolled on the shadcn `components/ui/table.tsx` primitives (TanStack Table is a dependency but currently unused — don't reach for it without cause).
- Sortable headers, multi-select with shift-range, bulk-action toolbar where the screen needs them.
- URL params for sort/filter (shareable view). Grouping helpers live in `lib/config-groups.ts` for banded config tables.

## Command palette

- Single `<CommandPalette>` instance mounted at root. Triggers on ⌘K globally.
- Commands registered via a hook: `useCommand({ name, group, action, shortcut })`.
- Recent commands surfaced first (LRU in localStorage).

## Auth

- `middleware.ts` checks Keycloak session on every route except `(auth)/`.
- Use `auth()` from next-auth in server components for session access.
- Role check in components: read role from session, conditionally render action affordances. Backend re-validates — never trust the client.

## Accessibility

- All interactive elements keyboard-navigable.
- Icons either `aria-label`-ed or `aria-hidden="true"`.
- Modals / drawers trap focus, restore on close.
- Status colour always paired with text or icon (never colour alone).
