#!/usr/bin/env bash
# scripts/db.sh — open a psql shell (or run one-off SQL) against the local dev
# Postgres running under Docker Compose (sasai-wallet-infra).
#
# No password: connections over the container's local socket are trusted for
# the POSTGRES_USER, so psql inside the container needs no credentials. User +
# DB names are the docker-compose dev defaults (see sasai-wallet-infra/).
#
# Usage:
#   scripts/db.sh                        # psql shell into wallet_platform (main dev DB)
#   scripts/db.sh test                   # psql shell into wallet_platform_test
#   scripts/db.sh <dbname>               # psql shell into an arbitrary database
#   scripts/db.sh -c "SELECT now();"     # run one statement against the main DB, exit
#   scripts/db.sh test -c "\dt"          # run against the test DB, exit
#   scripts/db.sh main -c "\d+ accounts" # inspect a table
set -euo pipefail

PG_USER="wallet"
DEFAULT_DB="wallet_platform"

# Find the running Postgres container. Matches the compose service by name so a
# different compose project prefix still resolves.
container="$(docker ps --filter 'name=postgres' --filter 'status=running' \
  --format '{{.Names}}' | head -n1 || true)"
if [[ -z "$container" ]]; then
  echo "No running Postgres container found. Start the stack first:" >&2
  echo "  cd sasai-wallet-infra && docker compose up -d postgres" >&2
  exit 1
fi

# A leading non-flag argument selects the database (with 'test'/'main' shortcuts);
# everything after it is passed straight through to psql.
db="$DEFAULT_DB"
if [[ $# -gt 0 && "${1:0:1}" != "-" ]]; then
  case "$1" in
    test) db="wallet_platform_test" ;;
    main) db="wallet_platform" ;;
    *) db="$1" ;;
  esac
  shift
fi

# Attach a TTY only when we actually have one, so `-c "..."` still works when
# the output is piped or captured.
tty_flags="-i"
if [[ -t 0 && -t 1 ]]; then
  tty_flags="-it"
fi

echo "→ psql as '${PG_USER}' on '${db}' (container: ${container})" >&2
exec docker exec "${tty_flags}" "${container}" psql -U "${PG_USER}" -d "${db}" "$@"
