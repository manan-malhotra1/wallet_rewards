# Sasai Mobile Simulator

Local-dev tool. Two seeded mobile wallets (Alice + Bob) side-by-side,
plus a Kafka/HTTP campaign-event trigger panel. Each user is logged in
from its pane by typing the seeded PIN (default `1234`).

## Setup

1. Backend running on `localhost:8000` with `SIMULATOR_DEV_MODE=true`
   in `backend/.env`.
2. `make seed` (in `backend/`) has been run. It seeds Alice + Bob with
   default PIN `1234` and registers the dev event source with a
   deterministic shared secret.
3. `cp .env.local.example .env.local` and adjust if needed (defaults
   already match the seed).

## Run

```bash
npm install
npm run dev      # serves on http://localhost:3002
```

## What lives where

- `app/page.tsx` — two-pane wallet view + event-trigger panel
- `app/_components/*` — wallet view, P2P form, event trigger, Partner APIs panel
- `app/_actions.ts` — server actions wrapping backend calls
- `lib/backend.ts` — backend client (PIN login, /me/wallet, P2P, events)
- `lib/hmac.ts` — X-Sasai-Signature builder
- `lib/config.ts` — env var loader

## Partner APIs panel

The "Partner APIs (external fund / withdraw)" card exercises the partner
external endpoints, which use **API-key + HMAC** auth (`X-Sasai-Api-Key` +
`X-Sasai-Signature` over `{ts}.{rawBody}`) instead of the user PIN/bearer flow
— the tenant is derived from the key. Three actions:

- **Fund** — `POST /api/v1/external/fund`: credit a target user's wallet.
- **Withdraw** — `POST /api/v1/external/withdraw`: debit a target user's
  wallet; supply an amount **or** toggle "Withdraw all" (exactly one).
- **Create user** — `POST /api/v1/external/users`: create a user from 1–2
  identifiers (at least one email/phone). Reports created (201) vs
  already-existing (200 — the identifier is the idempotency key).

The key id/secret come from `SASAI_API_KEY_ID` / `SASAI_API_KEY_SECRET` in
`.env.local` (dev defaults `sim-dev-key` / `dev-external-api-secret-do-not-use-in-prod`,
matching the dev key `make seed` provisions). Before that key is seeded a
**401** is expected; once seeded, fund/withdraw return a **422
`service_not_configured`** until a pricing+limits config exists (fail-closed) —
both are surfaced verbatim in the panel's response box, not treated as crashes.

## How the auth works

Each wallet pane has a login control. The operator types the user's PIN and
clicks **Log in**; the server action calls
`POST /api/v1/identity/auth/pin`, and on success the Next.js server holds the
PIN in a module-level credential store and caches the session token — both
server-side, so the browser never sees either. Subsequent actions (P2P,
cash-out, step-up, change-PIN) reuse the stored PIN, and an expired session
(401) is re-logged-in transparently. **Log out** clears the token + stored PIN
and invalidates the session server-side. There is no hardcoded default login
PIN; a logged-out pane hides its balances and forms until you log in. Because
both maps are in memory, restarting the dev server logs everyone out.

## Production caveat

This app is **dev-only**. The backend routes it relies on
(`/events/sim-ingest`, `/events/sim-kafka-produce`,
`/events/sim-bootstrap`) all 404 unless `SIMULATOR_DEV_MODE=true`.
Never deploy this app or set the flag in production.
