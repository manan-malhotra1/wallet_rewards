# Sasai Mobile Simulator

Local-dev tool. Two seeded mobile wallets (Alice + Bob) side-by-side,
plus a Kafka/HTTP campaign-event trigger panel. No login UI — the
simulator authenticates as the seeded users in the background.

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
- `app/_components/*` — wallet view, P2P form, event trigger
- `app/_actions.ts` — server actions wrapping backend calls
- `lib/backend.ts` — backend client (PIN login, /me/wallet, P2P, events)
- `lib/hmac.ts` — X-Sasai-Signature builder
- `lib/config.ts` — env var loader

## How the auth works

The simulator's Next.js server holds Alice + Bob's PINs (from
`.env.local`). On first request it does a silent
`POST /api/v1/identity/auth/pin` for each user, caches the session
token in memory, and reuses it. If a session expires (401) the
simulator drops the cache and re-logs in transparently.

## Production caveat

This app is **dev-only**. The backend routes it relies on
(`/events/sim-ingest`, `/events/sim-kafka-produce`,
`/events/sim-bootstrap`) all 404 unless `SIMULATOR_DEV_MODE=true`.
Never deploy this app or set the flag in production.
