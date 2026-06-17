#!/usr/bin/env bash
# Sasai Wallet — one script to start / stop / restart / inspect every
# local service (Docker stack + backend + admin UI).
#
# Usage:
#   scripts/dev.sh start      # bring everything up
#   scripts/dev.sh stop       # shut everything down
#   scripts/dev.sh restart    # stop + start
#   scripts/dev.sh status     # what's running on which port
#   scripts/dev.sh logs <svc> # tail backend|admin-ui|postgres|keycloak|redis|kafka
#
# Services managed:
#   - Docker compose stack in `sasai-wallet-infra/`
#       postgres (5432), kafka (9092), keycloak (8080), redis (6379), zookeeper (2181)
#   - Backend (FastAPI on :8000) via the project venv
#   - Admin UI (Next.js dev on :3000) via npm
#   - Mobile simulator (Next.js dev on :3002) via npm — dev-only test harness
#
# State:
#   - PIDs persisted under `.run/`
#   - Logs persisted under `.run/logs/`
#   - Both directories are .gitignored

set -euo pipefail

# --- Paths -------------------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
INFRA_DIR="${ROOT_DIR}/sasai-wallet-infra"
BACKEND_DIR="${ROOT_DIR}/backend"
UI_DIR="${ROOT_DIR}/admin-ui"
SIM_DIR="${ROOT_DIR}/mobile-simulator"
RUN_DIR="${ROOT_DIR}/.run"
LOG_DIR="${RUN_DIR}/logs"

BACKEND_PID="${RUN_DIR}/backend.pid"
UI_PID="${RUN_DIR}/admin-ui.pid"
SIM_PID="${RUN_DIR}/mobile-simulator.pid"
BACKEND_LOG="${LOG_DIR}/backend.log"
UI_LOG="${LOG_DIR}/admin-ui.log"
SIM_LOG="${LOG_DIR}/mobile-simulator.log"

mkdir -p "${RUN_DIR}" "${LOG_DIR}"

# --- Colours -----------------------------------------------------------------
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; RED=$'\033[31m'
  YELLOW=$'\033[33m'; BLUE=$'\033[34m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; GREEN=""; RED=""; YELLOW=""; BLUE=""; RESET=""
fi

info() { echo "${BLUE}»${RESET} $*"; }
ok()   { echo "${GREEN}✓${RESET} $*"; }
warn() { echo "${YELLOW}!${RESET} $*"; }
err()  { echo "${RED}✗${RESET} $*" >&2; }

# --- Helpers -----------------------------------------------------------------

# True when the given pidfile names a live process.
is_running() {
  local pidfile="$1"
  [[ -f "${pidfile}" ]] || return 1
  local pid
  pid="$(cat "${pidfile}")"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

# Anything listening on the given port? Returns the PID list.
port_holders() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
}

# Wait until a curl URL returns 2xx/3xx (or timeout). Quiet on success.
wait_for_http() {
  local url="$1" label="$2" attempts="${3:-30}"
  for ((i = 0; i < attempts; i++)); do
    if curl -fs -o /dev/null "${url}" 2>/dev/null; then
      ok "${label} ready"
      return 0
    fi
    sleep 1
  done
  err "${label} not ready after ${attempts}s"
  return 1
}

# Wait until a docker container reports healthy (or running, when no healthcheck).
wait_for_container() {
  local name="$1" attempts="${2:-30}"
  for ((i = 0; i < attempts; i++)); do
    local status
    status="$(docker inspect -f '{{.State.Health.Status}}' "${name}" 2>/dev/null || echo "")"
    if [[ "${status}" == "healthy" ]]; then
      ok "${name} healthy"
      return 0
    fi
    # Some images don't declare a healthcheck — accept "running" after a beat.
    if [[ -z "${status}" || "${status}" == "<no value>" ]]; then
      local running
      running="$(docker inspect -f '{{.State.Running}}' "${name}" 2>/dev/null || echo "")"
      if [[ "${running}" == "true" ]] && ((i > 5)); then
        ok "${name} running"
        return 0
      fi
    fi
    sleep 1
  done
  warn "${name} did not reach healthy in ${attempts}s — continuing"
  return 0
}

# --- Sub-commands ------------------------------------------------------------

cmd_start() {
  info "${BOLD}Sasai Wallet — start${RESET}"

  # 1. Host Postgres on 5432 will fight Docker for the port.
  local host_pg
  host_pg="$(port_holders 5432 | xargs -I{} sh -c 'ps -p {} -o comm=' 2>/dev/null | grep -v docker || true)"
  if [[ -n "${host_pg}" ]]; then
    warn "A host process is on :5432 (${host_pg})."
    warn "Stop it first or Docker Postgres can't bind. Try: brew services stop postgresql@18"
  fi

  # 2. Docker stack
  info "Bringing up Docker stack…"
  (cd "${INFRA_DIR}" && docker compose up -d) >/dev/null
  wait_for_container "sasai-wallet-infra-postgres-1" 30
  # Keycloak's first boot does Quarkus augmentation; cold start can hit ~90s.
  # Soft-fail: keep going so the backend + UI can come up even if keycloak
  # is slow — admin login will start working as soon as it's ready.
  wait_for_http "http://localhost:8080/realms/master" "keycloak" 180 || \
    warn "keycloak still warming — admin login will work once it's up"

  # 3. Backend
  if is_running "${BACKEND_PID}"; then
    warn "Backend already running (PID $(cat "${BACKEND_PID}"))"
  else
    info "Starting backend (uvicorn :8000)…"
    if [[ ! -d "${BACKEND_DIR}/.venv" ]]; then
      err "No venv at ${BACKEND_DIR}/.venv — run \`python -m venv .venv && pip install -r requirements.txt\` first."
      exit 1
    fi
    (
      cd "${BACKEND_DIR}"
      # shellcheck disable=SC1091
      source .venv/bin/activate
      nohup uvicorn app.main:app --port 8000 --log-level info \
        >"${BACKEND_LOG}" 2>&1 &
      echo $! >"${BACKEND_PID}"
    )
    wait_for_http "http://localhost:8000/healthz" "backend" 30
  fi

  # 4. Admin UI
  if is_running "${UI_PID}"; then
    warn "Admin UI already running (PID $(cat "${UI_PID}"))"
  else
    info "Starting admin UI (next dev :3000)…"
    if [[ ! -d "${UI_DIR}/node_modules" ]]; then
      err "No node_modules at ${UI_DIR} — run \`npm install\` first."
      exit 1
    fi
    (
      cd "${UI_DIR}"
      nohup npm run dev >"${UI_LOG}" 2>&1 &
      echo $! >"${UI_PID}"
    )
    # Next.js redirects unauth'd traffic with 307; treat that as ready.
    for ((i = 0; i < 60; i++)); do
      if curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 2>/dev/null | grep -qE '^(2|3)..'; then
        ok "admin UI ready"
        break
      fi
      sleep 1
    done
  fi

  # 5. Mobile simulator — optional. Only start when the directory exists
  # and an .env.local has been created. The backend MUST be running with
  # SIMULATOR_DEV_MODE=true for the sim's calls to succeed.
  if [[ -d "${SIM_DIR}" ]]; then
    if is_running "${SIM_PID}"; then
      warn "Mobile simulator already running (PID $(cat "${SIM_PID}"))"
    elif [[ ! -f "${SIM_DIR}/.env.local" ]]; then
      warn "Skipping mobile simulator — no ${SIM_DIR}/.env.local."
      warn "  Run: cp ${SIM_DIR}/.env.local.example ${SIM_DIR}/.env.local"
    elif [[ ! -d "${SIM_DIR}/node_modules" ]]; then
      warn "Skipping mobile simulator — no node_modules. Run \`npm install\` in ${SIM_DIR}."
    else
      info "Starting mobile simulator (next dev :3002)…"
      (
        cd "${SIM_DIR}"
        nohup npm run dev >"${SIM_LOG}" 2>&1 &
        echo $! >"${SIM_PID}"
      )
      for ((i = 0; i < 60; i++)); do
        if curl -s -o /dev/null -w "%{http_code}" http://localhost:3002 2>/dev/null | grep -qE '^(2|3)..'; then
          ok "mobile simulator ready"
          break
        fi
        sleep 1
      done
    fi
  fi

  echo
  cmd_status
}

cmd_stop() {
  info "${BOLD}Sasai Wallet — stop${RESET}"

  # Mobile simulator (stop first so it can't 5xx mid-shutdown when backend dies)
  if is_running "${SIM_PID}"; then
    local pid
    pid="$(cat "${SIM_PID}")"
    info "Stopping mobile simulator (PID ${pid})…"
    pkill -P "${pid}" 2>/dev/null || true
    kill "${pid}" 2>/dev/null || true
    rm -f "${SIM_PID}"
    ok "mobile simulator stopped"
  else
    local pids
    pids="$(port_holders 3002)"
    if [[ -n "${pids}" ]]; then
      info "Cleaning up stray :3002 listener(s) ${pids}"
      echo "${pids}" | xargs kill 2>/dev/null || true
    fi
  fi

  # Admin UI
  if is_running "${UI_PID}"; then
    local pid
    pid="$(cat "${UI_PID}")"
    info "Stopping admin UI (PID ${pid})…"
    # `next dev` spawns child workers — kill the whole process group.
    pkill -P "${pid}" 2>/dev/null || true
    kill "${pid}" 2>/dev/null || true
    rm -f "${UI_PID}"
    ok "admin UI stopped"
  else
    warn "admin UI not running (no pidfile)"
    # Fallback: kill anything on :3000 we don't know about.
    local pids
    pids="$(port_holders 3000)"
    if [[ -n "${pids}" ]]; then
      info "Cleaning up stray :3000 listener(s) ${pids}"
      echo "${pids}" | xargs kill 2>/dev/null || true
    fi
  fi

  # Backend
  if is_running "${BACKEND_PID}"; then
    local pid
    pid="$(cat "${BACKEND_PID}")"
    info "Stopping backend (PID ${pid})…"
    kill "${pid}" 2>/dev/null || true
    rm -f "${BACKEND_PID}"
    ok "backend stopped"
  else
    warn "backend not running (no pidfile)"
    local pids
    pids="$(port_holders 8000)"
    if [[ -n "${pids}" ]]; then
      info "Cleaning up stray :8000 listener(s) ${pids}"
      echo "${pids}" | xargs kill 2>/dev/null || true
    fi
  fi

  # Docker stack — keep volumes by default. Use `down --wipe` to drop them.
  info "Stopping Docker stack…"
  (cd "${INFRA_DIR}" && docker compose down) >/dev/null
  ok "Docker stack stopped"
}

cmd_restart() {
  cmd_stop
  echo
  cmd_start
}

# Print a pretty status table. Uses ANSI colours when stdout is a TTY.
cmd_status() {
  printf "${BOLD}%-14s %-12s %-32s %s${RESET}\n" "SERVICE" "PORT" "STATE" "EXTRA"
  printf "${DIM}%-14s %-12s %-32s %s${RESET}\n" "─────────────" "────────────" "──────────────────────────────" "─────"

  status_row() {
    local svc="$1" port="$2" check_cmd="$3" extra="${4:-}"
    if eval "${check_cmd}" >/dev/null 2>&1; then
      printf "%-14s %-12s ${GREEN}%-32s${RESET} %s\n" "${svc}" "${port}" "up" "${extra}"
    else
      printf "%-14s %-12s ${RED}%-32s${RESET} %s\n" "${svc}" "${port}" "down" "${extra}"
    fi
  }

  status_row "postgres" "5432" "docker exec sasai-wallet-infra-postgres-1 pg_isready -U wallet -d wallet_platform"
  status_row "redis"    "6379" "docker exec sasai-wallet-infra-redis-1 redis-cli ping"
  status_row "kafka"    "9092" "docker ps --filter name=sasai-wallet-infra-kafka-1 --filter status=running -q | grep -q ."
  status_row "keycloak" "8080" "curl -fs http://localhost:8080/realms/master"
  status_row "backend"  "8000" "curl -fs http://localhost:8000/healthz"
  status_row "admin-ui" "3000" "curl -fs -o /dev/null -w '%{http_code}' http://localhost:3000 | grep -qE '^(2|3)..'"
  status_row "mobile-sim" "3002" "curl -fs -o /dev/null -w '%{http_code}' http://localhost:3002 | grep -qE '^(2|3)..'" "dev-only"

  echo
  echo "${DIM}Logs:${RESET} ${LOG_DIR}/{backend,admin-ui,mobile-simulator}.log"
  echo "${DIM}Tail with:${RESET} scripts/dev.sh logs backend"
}

cmd_logs() {
  local svc="${1:-}"
  case "${svc}" in
    backend)  tail -n 80 -f "${BACKEND_LOG}" ;;
    admin-ui|ui|admin) tail -n 80 -f "${UI_LOG}" ;;
    mobile-sim|sim|simulator) tail -n 80 -f "${SIM_LOG}" ;;
    postgres) docker logs -f --tail 80 sasai-wallet-infra-postgres-1 ;;
    keycloak) docker logs -f --tail 80 sasai-wallet-infra-keycloak-1 ;;
    redis)    docker logs -f --tail 80 sasai-wallet-infra-redis-1 ;;
    kafka)    docker logs -f --tail 80 sasai-wallet-infra-kafka-1 ;;
    *)
      err "logs: pick one of backend | admin-ui | mobile-sim | postgres | keycloak | redis | kafka"
      exit 1
      ;;
  esac
}

usage() {
  cat <<EOF
${BOLD}Sasai Wallet — local dev script${RESET}

  ${BOLD}scripts/dev.sh start${RESET}      Bring everything up (Docker stack → backend → admin UI)
  ${BOLD}scripts/dev.sh stop${RESET}       Shut everything down (volumes preserved)
  ${BOLD}scripts/dev.sh restart${RESET}    Stop, then start
  ${BOLD}scripts/dev.sh status${RESET}     One-line health for each service
  ${BOLD}scripts/dev.sh logs <svc>${RESET} Tail one service's log
                       svc: backend | admin-ui | mobile-sim | postgres | keycloak | redis | kafka

State directories (gitignored):
  ${RUN_DIR}/    PID files
  ${LOG_DIR}/    backend.log, admin-ui.log, mobile-simulator.log
EOF
}

# --- Dispatch ----------------------------------------------------------------
cmd="${1:-status}"
case "${cmd}" in
  start)    cmd_start ;;
  stop)     cmd_stop ;;
  restart)  cmd_restart ;;
  status)   cmd_status ;;
  logs)     cmd_logs "${2:-}" ;;
  -h|--help|help) usage ;;
  *) usage; exit 1 ;;
esac
