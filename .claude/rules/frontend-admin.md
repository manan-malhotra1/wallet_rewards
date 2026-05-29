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

- In server components: directly call the API via the typed client in `lib/api/`. The Bearer token is read server-side from the Keycloak session.
- In client components: use server actions. Never `fetch` the backend directly from the browser.
- Never expose `BACKEND_URL` or `KEYCLOAK_CLIENT_SECRET` to the client. They are server-only env vars.

## Forms

- Server actions for submissions. Use `useFormState` + `useFormStatus` for pending/error states.
- Validation: zod schemas in `lib/schemas/`; reuse the same schema on server action to validate again.
- Inline validation on blur, not on every keystroke.
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

- TanStack Table v8.
- Sortable headers, multi-select with shift-range, bulk-action toolbar.
- 50 rows per page default. URL params for sort/filter (shareable view).

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
