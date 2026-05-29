# Sasai Wallet & Rewards Platform

A multi-tenant wallet + rule-based rewards engine for Sasai Fintech's diaspora ecosystem.

**Status:** Foundation scaffolded · 2026-05-28
**Owner:** Manan — Sasai Fintech

## Start here

1. Read [CLAUDE.md](CLAUDE.md) for the project's working context.
2. Read [docs/01-vision.md](docs/01-vision.md) for the why.
3. Read [docs/02-prd.md](docs/02-prd.md) for the what.
4. Read [docs/05-technical-architecture.md](docs/05-technical-architecture.md) and [docs/06-data-architecture.md](docs/06-data-architecture.md) for the how.
5. Read [docs/04-ui-layouts.md](docs/04-ui-layouts.md) for the admin UI design.
6. Skim [.claude/memory/MEMORY.md](.claude/memory/MEMORY.md) for architectural decisions.

## Local development

```bash
# 1. Infrastructure
cd infra && docker compose up -d
bash kafka/topics.sh
# Open http://localhost:8080, import keycloak/realm-export.json

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python ../scripts/seed.py
uvicorn app.main:app --reload --port 8000

# 3. Admin UI
cd admin-ui
npm install
cp .env.local.example .env.local
npm run dev      # :3000
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
├── infra/                      # Docker Compose (Kafka, Keycloak, Redis)
└── scripts/                    # Developer utilities (seed, check_migrations)
```

## License

Internal — Sasai Fintech. Confidential.
