#!/usr/bin/env bash
# Sasai Wallet — one-command mobile dev loop on the iOS simulator.
#
# Brings up everything the phone app needs and opens it, in order:
#   1. Docker infra + backend API        (delegated to scripts/dev.sh — idempotent)
#   2. Metro bundler on :8081            (mobile/, `expo start --dev-client`)
#   3. A booted iOS simulator            (boots one if none is running)
#   4. The Sasai Wallet dev client       (deep-linked at the local Metro)
#
# Usage:
#   scripts/mobile-dev.sh [start|stop|status|logs]     (default: start)
#
#   start  : start anything not already running, then open the app
#   stop   : stop Metro (backend/docker are left to scripts/dev.sh)
#   status : one-line health of backend / metro / simulator / app
#   logs   : tail the Metro log
#
# The dev client has no embedded JS — Metro must be up or the app shows
# "Could not connect to development server". First-time install of the dev
# client itself is a one-off `npm run ios` (this script tells you if missing).
#
# State: .run/metro.pid + .run/logs/metro.log (same convention as dev.sh).

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"
MOBILE_DIR="${ROOT_DIR}/mobile"
RUN_DIR="${ROOT_DIR}/.run"
LOG_DIR="${RUN_DIR}/logs"
METRO_PID="${RUN_DIR}/metro.pid"
METRO_LOG="${LOG_DIR}/metro.log"

METRO_PORT=8081
APP_BUNDLE_ID="com.sasai.wallet"
# Deep link that tells the dev client which Metro to load from.
DEV_CLIENT_URL="exp+sasai-wallet://expo-development-client/?url=http%3A%2F%2F127.0.0.1%3A${METRO_PORT}"
# Preferred simulator when none is booted (falls back to any available iPhone).
PREFERRED_DEVICE="iPhone 16 Pro"

mkdir -p "${LOG_DIR}"

info() { printf '\033[1;34m▸\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✔\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m⚠\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m✘\033[0m %s\n' "$*"; }

# --- Probes -------------------------------------------------------------------

metro_up() {
  curl -fs "http://localhost:${METRO_PORT}/status" 2>/dev/null | grep -q "packager-status:running"
}

backend_up() {
  # Any HTTP answer on :8000 means uvicorn is alive (404 on / is fine).
  curl -s -o /dev/null -m 3 "http://localhost:8000/openapi.json" 2>/dev/null
}

booted_sim() {
  xcrun simctl list devices booted 2>/dev/null | grep -oE '\([0-9A-F-]{36}\)' | head -1 | tr -d '()'
}

app_installed() {
  xcrun simctl get_app_container booted "${APP_BUNDLE_ID}" &>/dev/null
}

# --- Steps --------------------------------------------------------------------

start_backend_stack() {
  if backend_up; then
    ok "Backend already up on :8000"
  else
    info "Starting Docker infra + backend via scripts/dev.sh…"
    "${SCRIPT_DIR}/dev.sh" start docker
    "${SCRIPT_DIR}/dev.sh" start backend
  fi
}

start_metro() {
  if metro_up; then
    ok "Metro already serving on :${METRO_PORT}"
    return 0
  fi
  info "Starting Metro (expo start --dev-client)…"
  (
    cd "${MOBILE_DIR}" || exit 1
    nohup npm run start:dev >"${METRO_LOG}" 2>&1 &
    echo $! >"${METRO_PID}"
  )
  # Metro's first cold bundle can take minutes, but /status answers early.
  for _ in $(seq 1 60); do
    if metro_up; then
      ok "Metro is up (log: .run/logs/metro.log)"
      return 0
    fi
    sleep 1
  done
  fail "Metro didn't come up on :${METRO_PORT} — check ${METRO_LOG}"
  return 1
}

start_simulator() {
  local udid
  udid="$(booted_sim)"
  if [[ -n "${udid}" ]]; then
    ok "Simulator already booted (${udid})"
  else
    info "Booting ${PREFERRED_DEVICE}…"
    xcrun simctl boot "${PREFERRED_DEVICE}" 2>/dev/null \
      || xcrun simctl boot "$(xcrun simctl list devices available | grep -m1 -oE 'iPhone [^(]+' | head -1)" 2>/dev/null \
      || { fail "No bootable iPhone simulator found."; return 1; }
  fi
  open -a Simulator   # front the window either way
}

open_app() {
  if ! app_installed; then
    fail "Sasai Wallet dev client is not installed on this simulator."
    warn "One-time install: cd mobile && npm run ios   (then re-run this script)"
    return 1
  fi
  info "Opening Sasai Wallet against Metro…"
  xcrun simctl openurl booted "${DEV_CLIENT_URL}"
  ok "App launched. JS edits hot-reload; Ctrl+C here does NOT stop Metro (use: $0 stop)"
}

# --- Actions ------------------------------------------------------------------

do_start() {
  start_backend_stack
  start_metro || exit 1
  start_simulator || exit 1
  open_app
}

do_stop() {
  if [[ -f "${METRO_PID}" ]] && kill -0 "$(cat "${METRO_PID}")" 2>/dev/null; then
    kill "$(cat "${METRO_PID}")" 2>/dev/null
    rm -f "${METRO_PID}"
    ok "Metro stopped"
  else
    # Fall back to whatever owns the port (e.g. a Metro started by hand).
    local pid
    pid="$(lsof -tnP -i ":${METRO_PORT}" 2>/dev/null | head -1)"
    if [[ -n "${pid}" ]]; then
      kill "${pid}" && ok "Metro (pid ${pid}) stopped"
    else
      warn "Metro isn't running"
    fi
  fi
  warn "Backend/docker left running — stop them with: scripts/dev.sh stop"
}

do_status() {
  backend_up      && ok "backend  : up on :8000"            || fail "backend  : down"
  metro_up        && ok "metro    : up on :${METRO_PORT}"   || fail "metro    : down"
  local udid; udid="$(booted_sim)"
  [[ -n "${udid}" ]] && ok "simulator: booted (${udid})"     || fail "simulator: not booted"
  if [[ -n "${udid}" ]]; then
    app_installed && ok "app      : ${APP_BUNDLE_ID} installed" \
                  || fail "app      : not installed (cd mobile && npm run ios)"
  fi
}

do_logs() {
  [[ -f "${METRO_LOG}" ]] || { fail "No Metro log at ${METRO_LOG}"; exit 1; }
  tail -f "${METRO_LOG}"
}

case "${1:-start}" in
  start)  do_start ;;
  stop)   do_stop ;;
  status) do_status ;;
  logs)   do_logs ;;
  *) fail "Unknown action '${1}'. Usage: $0 [start|stop|status|logs]"; exit 1 ;;
esac
