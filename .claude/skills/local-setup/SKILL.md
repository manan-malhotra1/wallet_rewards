---
name: local-setup
description: First-time local setup + run of the whole stack (infra, backend, admin UI, mobile). Use when someone is setting up the project for the first time, when the local env is broken, or when they ask how to run/deploy locally, connect a phone/simulator, or dodge EAS build limits.
---

# /local-setup

End-to-end guide to run Sasai Wallet locally: infra → backend → admin UI → mobile
(simulator, emulator, and a physical phone). Follow top to bottom the first time;
jump to a section afterwards. Everything runs on the developer's Mac; only
Postgres/Kafka/Keycloak/Redis run in Docker.

## 0. Prerequisites (install once)

- **Docker Desktop** (infra stack)
- **Python 3.12** + `make`
- **Node 22** (`node -v`), `npm`
- Mobile (optional): **Xcode** (iOS sim) and/or **Android SDK** (`~/Library/Android/sdk`) + **JDK 17** (`brew install openjdk@17`), plus **CocoaPods** (`pod --version`) for local iOS builds
- `git`, and `curl` for health checks

Fix the one macOS gotcha up front — a past `sudo npm` leaves root-owned files in
`~/.npm` that break `npm`/EAS with `EACCES`:
```bash
sudo chown -R "$(whoami)" ~/.npm
```

## 1. Infra (Docker)

```bash
cd sasai-wallet-infra && docker compose up -d      # Postgres, Kafka, Keycloak, Redis
bash kafka/topics.sh                               # after Kafka is healthy
python ../scripts/bootstrap_keycloak.py            # provisions realm + admin clients
docker compose ps                                  # all services "Up"/"healthy"
```
Postgres: `localhost:5432` (`wallet` / `wallet` / db `wallet_platform`).

## 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                               # defaults are fine for local (OTP_DEV_RETURN=true)
alembic upgrade head
make seed                                           # test tenant, users, services, pricing, rules
make dev                                            # uvicorn --reload on :8000
```
Verify: `curl -s http://localhost:8000/healthz` → `{"status":"ok"}`.
`make check` = alembic check + ruff + mypy; `make test` = pytest (slow — one run at a time,
see the shared-test-DB note in §7).

**Seeded test accounts** (all PIN **`1234`**):
| Who | Phone | Type |
|---|---|---|
| Alice | `+27825550001` | consumer |
| Bob | `+27825550002` | consumer |
| Grace | `+27825558001` | agent (cash-in) |
Admin UI login (local dev): **`admin-test@example.test`** / **`admin-test-pass`**.

## 3. Admin UI

```bash
cd admin-ui
npm install
npm run dev                                         # :3000
```
Open `http://localhost:3000`, sign in with the admin dev creds above.
`npm test` runs the Vitest suite.

## 4. Mobile — the connectivity rule (read this first)

The app reads its backend URL from `EXPO_PUBLIC_BACKEND_URL`
(`mobile/lib/env.ts`): `process.env` (from `mobile/.env.development` in dev) →
`app.json` `expo.extra.backendUrl` → hard fallback `http://localhost:8000`. For
**EAS/baked builds** it comes from the EAS **environment** var
(`eas env:list --environment preview|development`), which OVERRIDES `app.json`.

**Pick the backend URL by target** (Mac backend runs on `:8000`):

| Target | `EXPO_PUBLIC_BACKEND_URL` | Why |
|---|---|---|
| **iOS simulator** | `http://localhost:8000` | sim shares the Mac loopback |
| **Android emulator** | `http://10.0.2.2:8000` | 10.0.2.2 = emulator's alias for host localhost |
| **Physical phone (same Wi‑Fi)** | `http://<Mac-LAN-IP>:8000` | e.g. `http://192.168.1.3:8000` — get it with `ipconfig getifaddr en0` |
| **Physical phone (any network / cleartext issues)** | the **HTTPS tunnel** URL | avoids Android cleartext-to-raw-IP blocks; works over mobile data |

Notes: the Mac LAN IP is DHCP and **drifts** — re-check `ipconfig getifaddr en0`
if the phone suddenly can't connect. Ensure the macOS firewall isn't blocking
`:8000`/`:8081` (`socketfilterfw --getglobalstate`). Some Samsung/Android phones
block **cleartext HTTP to a raw IP** even in dev → use the tunnel (below).

### HTTPS tunnel (for a physical phone / any network)
```bash
cloudflared tunnel --url http://localhost:8000      # prints https://<random>.trycloudflare.com
```
Put that URL in `mobile/.env.development` (or the EAS env for a baked build), then
restart Metro / rebuild. **Quick tunnels are ephemeral** — the URL changes on every
restart, so you re-point + reload each time. A **named** Cloudflare tunnel (needs a
`cloudflared tunnel login` + a domain you own) gives a stable URL.

## 5. Mobile — dev client (iterate WITHOUT spending EAS builds)

EAS cloud builds are quota-limited. Build a **dev client ONCE**, then every JS/UI
change hot-reloads over Metro — no more builds. Only a *native* change (new native
module, `app.json` native config, SDK bump) needs a rebuild. See
`mobile/DEV_CLIENT.md` for the full write-up.

**Build the dev client once** (pick one):
- Local, **0 cloud builds** (needs JDK 17 + Android SDK): `cd mobile && npm run build:devclient:android:local` → `adb install <the .apk>`
- Local iOS sim: `npx expo run:ios` (needs Xcode + CocoaPods; first build ~15–20 min)
- Cloud (1 build): `npm run build:devclient:android`

**Daily loop (no builds):**
```bash
# backend up on :8000 (make dev), .env.development set per §4
cd mobile && npm run start:dev            # Metro dev-client (same Wi‑Fi)
#            npm run start:dev:tunnel      # Metro over a tunnel (any network)
```
- **Android emulator:** `adb reverse tcp:8081 tcp:8081` (Metro) and optionally
  `adb reverse tcp:8000 tcp:8000` (then use `localhost:8000`); open the dev client → it loads from Metro.
- **iOS simulator:** connects to Metro on `localhost:8081` automatically.
- **Physical phone:** open the dev client → enter Metro `http://<Mac-LAN-IP>:8081` (same Wi‑Fi). Edit JS → shake → **Reload**.

Changing `mobile/.env.development` requires a **Metro restart** (`--clear`) to rebundle.

## 6. Mobile — a standalone/simulator build via EAS (snapshot, no Metro)

For a self-contained build (JS baked in, no hot-reload):
```bash
# iOS simulator build → localhost backend:
cd mobile
eas env:update --variable-name EXPO_PUBLIC_BACKEND_URL --variable-environment preview \
  --value http://localhost:8000 --visibility plaintext --non-interactive
eas build --platform ios --profile preview-simulator --non-interactive --no-wait
# when FINISHED: download the .tar.gz artifact, untar the .app, then:
xcrun simctl boot <iphone-udid>; open -a Simulator
xcrun simctl install <udid> SasaiWallet.app
xcrun simctl launch <udid> com.sasai.wallet
# Android APK (physical device): profile `preview`; bake the tunnel URL into the EAS env instead of localhost.
```
The EAS `preview` environment is SHARED by `preview` (Android APK) and
`preview-simulator` (iOS) — set the URL to match the target before building
(localhost for the sim, tunnel for a real Android phone).

## 7. Dev conveniences + gotchas (things that will bite you)

- **Dev OTP:** no SMS in dev. `otp/send` returns the code (`OTP_DEV_RETURN=true`) and the
  mobile OTP screen shows **"Dev OTP: 123456"**. Type that in.
- **Airtime "simulated provider failure":** the sim provider FAILS for any recharge
  number ending `...0001` (and PENDING for `...0002`). For dev, set the airtime
  merchant's `provider_config.force_outcome = "success"` (seeded) or recharge a
  non-`0001` number.
- **Referral codes:** seeded users may lack a `referral_codes` row (the seed builds
  users directly, bypassing `create_user`'s generator). If a user has no code, backfill
  (generate a unique 8-char code per user) or re-seed. Dev signup-referral reward fires
  **at PIN-set** (verified, completed signup) — enter a code at "Create account", verify
  OTP, set PIN → both sides earn.
- **Receive-limit 409 (`recipient_limit_reached`):** the recipient hit a rolling
  daily/weekly/monthly RECEIVE cap (values live in `wallet_limit_configs`). Send to a
  fresh/low-volume recipient, or raise the cap. Not a bug.
- **Shared test DB:** all pytest runs hit ONE Postgres test DB — run **one suite at a
  time**; concurrent runs (multiple sessions/agents) deadlock and hang. `pkill` only your
  own stuck runs.
- **`npm`/EAS `EACCES … _cacache`:** root-owned npm cache — `sudo chown -R "$(whoami)" ~/.npm`.
- **Reset a user's PIN in dev:** `UPDATE users SET pin_hash=<bcrypt('1234')> WHERE …` (use
  `app.auth.hashing.hash_pin` to generate the hash — the app uses `bcrypt`, not passlib).

## 8. Quick "is it all up?" check

```bash
curl -s http://localhost:8000/healthz            # backend
curl -s http://localhost:3000 >/dev/null && echo "admin UI up"
docker compose -f sasai-wallet-infra/docker-compose.yml ps   # infra
curl -s http://localhost:8081/status             # Metro (if running)
```

**Source of truth:** `CLAUDE.md` (commands), `mobile/DEV_CLIENT.md` (dev-client loop),
`docs/05-technical-architecture.md`.
