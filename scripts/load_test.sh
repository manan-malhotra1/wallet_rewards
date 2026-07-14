#!/usr/bin/env bash
#
# load_test.sh - sustained-TPS load test against a running backend.
#
# Thin wrapper over scripts/load_test_p2p.py: uses the backend venv and runs a
# 5-minute, 50-concurrency P2P load by default. Every flag passes through to the
# Python script (CLI flags win over the env defaults below), so `--help` is the
# full reference.
#
# What it does: authenticates as platform-admin, ensures N load users + ZAR
# wallets, funds them, then fires random P2P transfers at the target concurrency
# for the chosen duration - printing rolling TPS and a final latency/error
# report. Setup is idempotent (cached in --state-file), so re-runs skip
# provisioning.
#
# Prerequisites (local dev stack):
#   - infra up   : cd sasai-wallet-infra && docker compose up -d
#   - backend up : cd backend && make dev              (server on :8000)
#   - venv ready : backend/.venv with requirements installed
#
# Usage:
#   scripts/load_test.sh                        # 5 min - 50 concurrency - 500 users
#   scripts/load_test.sh --duration 60          # 1-minute smoke test
#   scripts/load_test.sh --concurrency 100 --users 2000
#   DURATION=600 scripts/load_test.sh           # env override (10-minute run)
#   scripts/load_test.sh --phase setup          # only provision users, no load
#   scripts/load_test.sh --help                 # all flags (from the Python script)
#
# Env overrides: API_URL, DURATION, CONCURRENCY, USERS (explicit CLI flags win).
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
SCRIPT="$ROOT/scripts/load_test_p2p.py"

API_URL="${API_URL:-http://localhost:8000}"
DURATION="${DURATION:-300}"        # 5 minutes
CONCURRENCY="${CONCURRENCY:-50}"
USERS="${USERS:-500}"

# `-h` / `--help` -> defer to the Python script's full flag reference.
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  exec "$PY" "$SCRIPT" --help
fi

# Preflight: fail early with an actionable message instead of a deep traceback.
if [[ ! -x "$PY" ]]; then
  echo "error: backend venv not found at $PY" >&2
  echo "  fix: cd backend && python -m venv .venv && pip install -r requirements.txt" >&2
  exit 1
fi
# curl exits 0 for any HTTP response (even 404); non-zero only on connection refusal.
if ! curl -s --max-time 3 -o /dev/null "$API_URL"; then
  echo "error: backend not reachable at $API_URL" >&2
  echo "  fix: cd backend && make dev   (and: cd sasai-wallet-infra && docker compose up -d)" >&2
  exit 1
fi

echo ">> load test -> $API_URL  (duration=${DURATION}s concurrency=${CONCURRENCY} users=${USERS})"
# Defaults first, then "$@" so any explicit flag the caller passes overrides them.
exec "$PY" "$SCRIPT" \
  --api-url "$API_URL" \
  --duration "$DURATION" \
  --concurrency "$CONCURRENCY" \
  --users "$USERS" \
  "$@"
