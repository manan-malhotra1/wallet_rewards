# Sasai Wallet & Rewards Platform

A multi-tenant wallet + rule-based rewards engine for Sasai Fintech's diaspora ecosystem.

**Status:** Phase F.5 shipped · admin UI scaffolded · 2026-06-16
**Owner:** Manan — Sasai Fintech

## Start here

1. Read [CLAUDE.md](CLAUDE.md) for the project's working context.
2. Read [docs/01-vision.md](docs/01-vision.md) for the why.
3. Read [docs/02-prd.md](docs/02-prd.md) for the what.
4. Read [docs/05-technical-architecture.md](docs/05-technical-architecture.md) and [docs/06-data-architecture.md](docs/06-data-architecture.md) for the how.
5. Read [docs/04-ui-layouts.md](docs/04-ui-layouts.md) for the admin UI design.
6. Skim [.claude/memory/MEMORY.md](.claude/memory/MEMORY.md) for architectural decisions.

## Local development

Everything except the backend Python interpreter + the admin UI Node
toolchain runs in Docker. No host-installed Postgres / Redis / Keycloak /
Kafka.

```bash
# 1. Bring up infrastructure (Postgres, Kafka, Keycloak, Redis)
cd sasai-wallet-infra && docker compose up -d
bash kafka/topics.sh           # after Kafka is healthy (~10s)
python ../scripts/bootstrap_keycloak.py   # provision realm + clients

# 2. Backend
cd ../backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
make seed
make dev                       # uvicorn at :8000

# 3. Admin UI
cd ../admin-ui
npm install
cp .env.local.example .env.local
npm run dev                    # :3000
```

## Repository layout

```
Sasai_Wallet/
├── CLAUDE.md                   # Project context (read first)
├── README.md
├── docs/                       # Strategic + technical docs
├── .claude/                    # Agents, skills, rules, memory
├── backend/                    # Python FastAPI monolith
├── admin-ui/                   # Next.js 16 admin dashboard
├── sasai-wallet-infra/         # Docker Compose (Postgres, Kafka, Keycloak, Redis)
└── scripts/                    # Developer utilities (seed, check_migrations,
                                #   bootstrap_keycloak, publish_event, run_consumer)
```

## License

Internal — Sasai Fintech. Confidential.
