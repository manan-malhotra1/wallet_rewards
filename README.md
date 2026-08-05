# Sasai Wallet & Rewards Platform

A multi-tenant **wallet + rule-based rewards engine** for Sasai Fintech's diaspora ecosystem. Three per-tenant
deployment modes (`business_type`: wallet / rewards / both), an append-only double-entry ledger, Kafka-backed
event ingestion, a Keycloak-secured admin UI, PIN/OTP for end users, and an Expo mobile app.

**Status:** as-built through 2026-08-05 · backend + admin UI + mobile live
**Owner:** Manan — Sasai Fintech

---

## Get the code

```bash
git clone https://github.com/manan-malhotra1/wallet_rewards.git
cd wallet_rewards
```

Repository (open in a browser): **https://github.com/manan-malhotra1/wallet_rewards**

---

## Start here (docs)

1. [CLAUDE.md](CLAUDE.md) — the project's working context (read first).
2. [docs/01-vision.md](docs/01-vision.md) — the *why*.
3. [docs/02-prd.md](docs/02-prd.md) — the *what* (product requirements, `Pay-PRD-####` IDs + acceptance criteria).
4. [docs/09-epics-and-stories.md](docs/09-epics-and-stories.md) — delivery tracking (what's Shipped / Partial / Planned).
5. [docs/design/README.md](docs/design/README.md) — the *how* (high-level design + per-module implementation docs).
6. [docs/05-technical-architecture.md](docs/05-technical-architecture.md) · [docs/06-data-architecture.md](docs/06-data-architecture.md) — system-level architecture.
7. [docs/03-ux-philosophy.md](docs/03-ux-philosophy.md) · [docs/04-ui-layouts.md](docs/04-ui-layouts.md) — admin UI design.
8. [.claude/memory/MEMORY.md](.claude/memory/MEMORY.md) — architectural decisions log.

---

## Local setup

End-to-end guide to run the whole stack on one machine: **infra → backend → admin UI → mobile**. Only
Postgres / Kafka / Keycloak / Redis run in Docker; the backend Python interpreter, the admin Node toolchain, and
the mobile app run on your host. This mirrors the [`local-setup`](.claude/skills/local-setup/SKILL.md) skill —
see it (and [mobile/DEV_CLIENT.md](mobile/DEV_CLIENT.md)) for the deeper mobile / dev-client detail.

### 0. Prerequisites (install once)

- **Docker Desktop** (infra stack)
- **Python 3.12** + `make`
- **Node 22** (`node -v`) + `npm`
- Mobile (optional): **Xcode** (iOS sim) and/or **Android SDK** (`~/Library/Android/sdk`) + **JDK 17**
  (`brew install openjdk@17`), plus **CocoaPods** for local iOS builds
- `git`, and `curl` for health checks

macOS gotcha to fix up front — a past `sudo npm` leaves root-owned files in `~/.npm` that break `npm`/EAS:
```bash
sudo chown -R "$(whoami)" ~/.npm
```

### 1. Infrastructure (Docker)

```bash
cd sasai-wallet-infra && docker compose up -d      # Postgres, Kafka, Keycloak, Redis
bash kafka/topics.sh                               # after Kafka is healthy (~10s)
python ../scripts/bootstrap_keycloak.py            # provisions the realm + admin clients
docker compose ps                                  # all services "Up" / "healthy"
```
Postgres: `localhost:5432` (`wallet` / `wallet` / db `wallet_platform`).

### 2. Backend

```bash
cd ../backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                               # defaults are fine for local (OTP_DEV_RETURN=true)
alembic upgrade head
make seed                                           # test tenant, users, services, pricing, rules
make dev                                            # uvicorn --reload on :8000
```
Verify: `curl -s http://localhost:8000/healthz` → `{"status":"ok"}`.
`make check` = alembic check + ruff + mypy; `make test` = pytest (slow — run **one suite at a time**; the test
DB is shared and concurrent runs deadlock).

**Seeded test accounts** (all PIN **`1234`**):

| Who | Phone | Type |
|---|---|---|
| Alice | `+27825550001` | consumer |
| Bob | `+27825550002` | consumer |
| Grace | `+27825558001` | agent (cash-in) |

Admin UI login (local dev): **`admin-test@example.test`** / **`admin-test-pass`**.

### 3. Admin UI

```bash
cd ../admin-ui
npm install
cp .env.local.example .env.local                   # Keycloak creds match bootstrap_keycloak.py (copy-and-go)
npm run dev                                         # :3000
```
Open `http://localhost:3000` and sign in with the admin dev creds above. `npm test` runs the Vitest suite.

### 4. Mobile (optional) — pick the backend URL by target

The app reads its backend URL from `EXPO_PUBLIC_BACKEND_URL` (`mobile/.env.development`). The Mac backend runs
on `:8000`:

| Target | `EXPO_PUBLIC_BACKEND_URL` | Why |
|---|---|---|
| **iOS simulator** | `http://localhost:8000` | sim shares the Mac loopback |
| **Android emulator** | `http://10.0.2.2:8000` | `10.0.2.2` = emulator's alias for host localhost |
| **Physical phone (same Wi-Fi)** | `http://<Mac-LAN-IP>:8000` | e.g. `http://192.168.1.3:8000` (`ipconfig getifaddr en0`) |
| **Physical phone (any network / cleartext issues)** | an **HTTPS tunnel** URL | `cloudflared tunnel --url http://localhost:8000` (ephemeral) |

Iterate without spending EAS build credits: build a **dev client once**, then every JS/UI change hot-reloads
over Metro (`cd mobile && npm run start:dev`). See [mobile/DEV_CLIENT.md](mobile/DEV_CLIENT.md).

### 5. "Is it all up?" check

```bash
curl -s http://localhost:8000/healthz                          # backend
curl -s http://localhost:3000 >/dev/null && echo "admin UI up" # admin UI
docker compose -f sasai-wallet-infra/docker-compose.yml ps     # infra
```

### Dev gotchas (things that will bite you)

- **Dev OTP:** no SMS in dev — `otp/send` returns the code and the mobile OTP screen shows **"Dev OTP: 123456"**.
- **Airtime "simulated provider failure":** the sim provider fails for recharge numbers ending `...0001`. Use a
  non-`0001` number or set the airtime merchant's `provider_config.force_outcome = "success"` (seeded).
- **Receive-limit 409 (`recipient_limit_reached`):** the recipient hit a rolling receive cap — send to a
  fresh/low-volume recipient, or raise the cap in `/limits`. Not a bug.
- **`npm`/EAS `EACCES … _cacache`:** root-owned npm cache → `sudo chown -R "$(whoami)" ~/.npm`.
- **Shared test DB:** run one pytest suite at a time; concurrent runs deadlock.

---

## Repository layout

```
wallet_rewards/
├── CLAUDE.md                   # Project context (read first)
├── README.md
├── docs/                       # Vision, PRD, epics, design/ (per-module HOW), architecture, UX/UI, security
├── .claude/                    # Agents, skills (incl. local-setup), rules, memory
├── backend/                    # Python FastAPI monolith (~27 modules)
├── admin-ui/                   # Next.js 16 admin dashboard
├── mobile/                     # Expo (React Native) end-user app
├── sasai-wallet-infra/         # Docker Compose (Postgres, Kafka, Keycloak, Redis)
└── scripts/                    # seed, check_migrations, bootstrap_keycloak, run_consumer
```

## License

Internal — Sasai Fintech. Confidential.
