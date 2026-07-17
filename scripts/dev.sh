#!/usr/bin/env bash
# Sasai Wallet — one script to start / stop / restart / inspect every
# local service, together OR independently.
#
# Usage:
#   scripts/dev.sh <action> [service]
#     action  : start | stop | restart | status | logs
#     service : docker | backend | admin-ui | sim | all   (default: all)
#
# Examples:
#   scripts/dev.sh start                # bring the whole stack up (docker → backend → ui → sim)
#   scripts/dev.sh start backend        # start only the API
#   scripts/dev.sh restart admin-ui     # bounce only the admin UI
#   scripts/dev.sh stop sim             # stop only the mobile simulator
#   scripts/dev.sh restart docker       # restart only the Docker infra stack
#   scripts/dev.sh status               # health of everything
#   scripts/dev.sh logs backend         # tail one service's log
#
# Service aliases: ui|admin → admin-ui ; mobile-sim|simulator → sim
#
# Services managed:
#   - docker    : compose stack in `sasai-wallet-infra/`
#                 postgres (5432), kafka (9092), keycloak (8080), redis (6379), zookeeper (2181)
#   - backend   : FastAPI on :8000 (project venv)
#   - admin-ui  : Next.js dev on :3000 (npm)
#   - sim       : Next.js mobile simulator on :3002 (npm) — dev-only harness
#
# State: PIDs under `.run/`, logs under `.run/logs/` (both .gitignored).

set -uo pipefail

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

# Normalise a service alias to its canonical name (or "all").
canon_service() {
  case "${1:-all}" in
    docker) echo docker ;;
    backend|api) echo backend ;;
    admin-ui|ui|admin) echo admin-ui ;;
    sim|mobile-sim|simulator|mobile) echo sim ;;
    all|"") echo all ;;
    *) echo "UNKNOWN" ;;
  esac
}

# --- Per-service START -------------------------------------------------------

start_docker() {
  # Warn if a host Postgres is squatting on :5432 (would block Docker's bind).
  local host_pg
  host_pg="$(port_holders 5432 | xargs -I{} sh -c 'ps -p {} -o comm=' 2>/dev/null | grep -v docker || true)"
  if [[ -n "${host_pg}" ]]; then
    warn "A host process is on :5432 (${host_pg}). Try: brew services stop postgresql@18"
  fi
  info "Bringing up Docker stack…"
  (cd "${INFRA_DIR}" && docker compose up -d) >/dev/null
  wait_for_container "sasai-wallet-infra-postgres-1" 30
  # Keycloak cold start can hit ~90s; soft-fail so the rest can proceed.
  wait_for_http "http://localhost:8080/realms/master" "keycloak" 180 || \
    warn "keycloak still warming — admin login will work once it's up"
}

start_backend() {
  if is_running "${BACKEND_PID}"; then
    warn "Backend already running (PID $(cat "${BACKEND_PID}"))"; return 0
  fi
  if [[ ! -d "${BACKEND_DIR}/.venv" ]]; then
    err "No venv at ${BACKEND_DIR}/.venv — run \`python -m venv .venv && pip install -r requirements.txt\` first."
    return 1
  fi
  info "Starting backend (uvicorn :8000)…"
  (
    cd "${BACKEND_DIR}"
    # shellcheck disable=SC1091
    source .venv/bin/activate
    nohup uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --log-level info \
      >"${BACKEND_LOG}" 2>&1 &
    echo $! >"${BACKEND_PID}"
  )
  wait_for_http "http://localhost:8000/healthz" "backend" 30 || true
}

start_ui() {
  if is_running "${UI_PID}"; then
    warn "Admin UI already running (PID $(cat "${UI_PID}"))"; return 0
  fi
  if [[ ! -d "${UI_DIR}/node_modules" ]]; then
    err "No node_modules at ${UI_DIR} — run \`npm install\` first."; return 1
  fi
  info "Starting admin UI (next dev :3000)…"
  (
    cd "${UI_DIR}"
    nohup npm run dev >"${UI_LOG}" 2>&1 &
    echo $! >"${UI_PID}"
  )
  for ((i = 0; i < 60; i++)); do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 2>/dev/null | grep -qE '^(2|3)..'; then
      ok "admin UI ready"; break
    fi
    sleep 1
  done
}

start_sim() {
  if [[ ! -d "${SIM_DIR}" ]]; then warn "No mobile-simulator directory — skipping."; return 0; fi
  if is_running "${SIM_PID}"; then
    warn "Mobile simulator already running (PID $(cat "${SIM_PID}"))"; return 0
  fi
  if [[ ! -f "${SIM_DIR}/.env.local" ]]; then
    warn "Skipping mobile simulator — no ${SIM_DIR}/.env.local (cp .env.local.example .env.local)."; return 0
  fi
  if [[ ! -d "${SIM_DIR}/node_modules" ]]; then
    warn "Skipping mobile simulator — no node_modules (run \`npm install\` in ${SIM_DIR})."; return 0
  fi
  info "Starting mobile simulator (next dev :3002)…"
  (
    cd "${SIM_DIR}"
    nohup npm run dev >"${SIM_LOG}" 2>&1 &
    echo $! >"${SIM_PID}"
  )
  for ((i = 0; i < 60; i++)); do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:3002 2>/dev/null | grep -qE '^(2|3)..'; then
      ok "mobile simulator ready"; break
    fi
    sleep 1
  done
}

# --- Per-service STOP --------------------------------------------------------

# Stop a Node dev server (kills child workers too) by pidfile, with a port fallback.
_stop_node() {
  local label="$1" pidfile="$2" port="$3"
  if is_running "${pidfile}"; then
    local pid; pid="$(cat "${pidfile}")"
    info "Stopping ${label} (PID ${pid})…"
    pkill -P "${pid}" 2>/dev/null || true
    kill "${pid}" 2>/dev/null || true
    rm -f "${pidfile}"
    ok "${label} stopped"
  else
    local pids; pids="$(port_holders "${port}")"
    if [[ -n "${pids}" ]]; then
      info "Cleaning up stray :${port} listener(s) ${pids}"
      echo "${pids}" | xargs kill 2>/dev/null || true
    else
      warn "${label} not running (:${port})"
    fi
  fi
}

stop_sim()     { _stop_node "mobile simulator" "${SIM_PID}" 3002; }
stop_ui()      { _stop_node "admin UI" "${UI_PID}" 3000; }

stop_backend() {
  if is_running "${BACKEND_PID}"; then
    local pid; pid="$(cat "${BACKEND_PID}")"
    info "Stopping backend (PID ${pid})…"
    kill "${pid}" 2>/dev/null || true
    rm -f "${BACKEND_PID}"
    ok "backend stopped"
  else
    local pids; pids="$(port_holders 8000)"
    if [[ -n "${pids}" ]]; then
      info "Cleaning up stray :8000 listener(s) ${pids}"
      echo "${pids}" | xargs kill 2>/dev/null || true
    else
      warn "backend not running (:8000)"
    fi
  fi
}

stop_docker() {
  info "Stopping Docker stack…"
  (cd "${INFRA_DIR}" && docker compose down) >/dev/null
  ok "Docker stack stopped"
}

# --- Actions (dispatch over a target service) --------------------------------

cmd_start() {
  local target="$1"
  info "${BOLD}Sasai Wallet — start${RESET} (${target})"
  case "${target}" in
    docker) start_docker ;;
    backend) start_backend ;;
    admin-ui) start_ui ;;
    sim) start_sim ;;
    all) start_docker; start_backend; start_ui; start_sim ;;
  esac
  echo
  cmd_status
}

cmd_stop() {
  local target="$1"
  info "${BOLD}Sasai Wallet — stop${RESET} (${target})"
  case "${target}" in
    docker) stop_docker ;;
    backend) stop_backend ;;
    admin-ui) stop_ui ;;
    sim) stop_sim ;;
    # Apps first, then docker, so nothing 5xx's mid-shutdown.
    all) stop_sim; stop_ui; stop_backend; stop_docker ;;
  esac
}

cmd_restart() {
  local target="$1"
  cmd_stop "${target}"
  echo
  cmd_start "${target}"
}

# Print a pretty status table (all services regardless of target).
cmd_status() {
  printf "${BOLD}%-14s %-8s %-8s %s${RESET}\n" "SERVICE" "PORT" "STATE" "EXTRA"
  printf "${DIM}%-14s %-8s %-8s %s${RESET}\n" "─────────────" "──────" "──────" "─────"

  status_row() {
    local svc="$1" port="$2" check_cmd="$3" extra="${4:-}"
    if eval "${check_cmd}" >/dev/null 2>&1; then
      printf "%-14s %-8s ${GREEN}%-8s${RESET} %s\n" "${svc}" "${port}" "up" "${extra}"
    else
      printf "%-14s %-8s ${RED}%-8s${RESET} %s\n" "${svc}" "${port}" "down" "${extra}"
    fi
  }

  status_row "postgres" "5432" "docker exec sasai-wallet-infra-postgres-1 pg_isready -U wallet -d wallet_platform" "docker"
  status_row "redis"    "6379" "docker exec sasai-wallet-infra-redis-1 redis-cli ping" "docker"
  status_row "kafka"    "9092" "docker ps --filter name=sasai-wallet-infra-kafka-1 --filter status=running -q | grep -q ." "docker"
  status_row "keycloak" "8080" "curl -fs http://localhost:8080/realms/master" "docker"
  status_row "backend"  "8000" "curl -fs http://localhost:8000/healthz"
  status_row "admin-ui" "3000" "curl -fs -o /dev/null -w '%{http_code}' http://localhost:3000 | grep -qE '^(2|3)..'"
  status_row "sim"      "3002" "curl -fs -o /dev/null -w '%{http_code}' http://localhost:3002 | grep -qE '^(2|3)..'" "dev-only"

  echo
  echo "${DIM}Logs:${RESET} scripts/dev.sh logs <backend|admin-ui|sim|postgres|keycloak|redis|kafka>"
}

cmd_logs() {
  local svc; svc="$(canon_service "${1:-}")"
  case "${svc}" in
    backend)  tail -n 80 -f "${BACKEND_LOG}" ;;
    admin-ui) tail -n 80 -f "${UI_LOG}" ;;
    sim)      tail -n 80 -f "${SIM_LOG}" ;;
    docker)   (cd "${INFRA_DIR}" && docker compose logs -f --tail 80) ;;
    *)
      # Allow the raw container names too.
      case "${1:-}" in
        postgres) docker logs -f --tail 80 sasai-wallet-infra-postgres-1 ;;
        keycloak) docker logs -f --tail 80 sasai-wallet-infra-keycloak-1 ;;
        redis)    docker logs -f --tail 80 sasai-wallet-infra-redis-1 ;;
        kafka)    docker logs -f --tail 80 sasai-wallet-infra-kafka-1 ;;
        *) err "logs: pick backend | admin-ui | sim | docker | postgres | keycloak | redis | kafka"; exit 1 ;;
      esac
      ;;
  esac
}

usage() {
  cat <<EOF
${BOLD}Sasai Wallet — local dev script${RESET}

  scripts/dev.sh <action> [service]
    action  : start | stop | restart | status | logs
    service : docker | backend | admin-ui | sim | all   (default: all)

Examples:
  scripts/dev.sh start                 whole stack up
  scripts/dev.sh start backend         API only
  scripts/dev.sh restart admin-ui      bounce the admin UI only
  scripts/dev.sh stop sim              stop the simulator only
  scripts/dev.sh restart docker        restart infra only
  scripts/dev.sh status                health of everything
  scripts/dev.sh logs backend          tail one log

State (gitignored): ${RUN_DIR}/ (PIDs), ${LOG_DIR}/ (logs)
EOF
}

# --- Dispatch ----------------------------------------------------------------
action="${1:-status}"
target="$(canon_service "${2:-all}")"

if [[ "${target}" == "UNKNOWN" ]]; then
  err "unknown service '${2:-}' — use docker | backend | admin-ui | sim | all"
  exit 1
fi

case "${action}" in
  start)   cmd_start "${target}" ;;
  stop)    cmd_stop "${target}" ;;
  restart) cmd_restart "${target}" ;;
  status)  cmd_status ;;
  logs)    cmd_logs "${2:-}" ;;
  -h|--help|help) usage ;;
  *) usage; exit 1 ;;
esac
