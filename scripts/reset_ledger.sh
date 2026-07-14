#!/usr/bin/env bash
#
# scripts/reset_ledger.sh - DEV/LOCAL ONLY: wipe all money movement and balances.
#
# Zeroes every user + system wallet by TRUNCATing the money-movement tables.
# Balance is derived as SUM(ledger_entries) (plus the account_balance_snapshots
# cache), so clearing those tables zeroes every balance. Account/user/tenant/
# config rows are KEPT - only the financial history is removed.
#
# !! DANGER !! This DELETES the append-only ledger + transactions. That violates
# the 7-year retention invariant (NFR-0150) and the append-only rule
# (ledger-invariants.md #1). It exists ONLY to reset a local dev database (e.g.
# after load testing). It runs exclusively against the local Docker Postgres via
# scripts/db.sh - there is deliberately no way to point it at a remote host.
# NEVER adapt it to run against production.
#
# Wipes   : transactions, ledger_entries, account_balance_snapshots,
#           airtime_recharges, redemptions, reward_events (+ anything FK-CASCADEd).
# Keeps   : accounts, users, tenants, pricing/limit configs, roles, services,
#           audit_log (immutable - retained on purpose).
#
# Usage:
#   scripts/reset_ledger.sh              # reset main dev DB (wallet_platform), interactive confirm
#   scripts/reset_ledger.sh test         # reset the test DB (wallet_platform_test)
#   scripts/reset_ledger.sh main -y      # skip the confirm prompt (for scripted use)
#
# After a reset, re-seed opening data if you want it:  cd backend && make seed
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- args: [main|test] and optional -y/--yes ---------------------------------
# Only the two known dev databases are allowed - a guardrail against pointing
# this at anything unexpected.
DB_ARG="main"
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    main|test) DB_ARG="$arg" ;;
    *) echo "usage: reset_ledger.sh [main|test] [-y|--yes]" >&2; exit 2 ;;
  esac
done

# Children -> parents; CASCADE is the safety net for any FK dependent not listed.
TABLES="reward_events, redemptions, airtime_recharges, ledger_entries, transactions, account_balance_snapshots"

COUNT_SQL="
SELECT 'transactions'              AS table, count(*) FROM transactions
UNION ALL SELECT 'ledger_entries',            count(*) FROM ledger_entries
UNION ALL SELECT 'account_balance_snapshots', count(*) FROM account_balance_snapshots
UNION ALL SELECT 'airtime_recharges',         count(*) FROM airtime_recharges
UNION ALL SELECT 'redemptions',               count(*) FROM redemptions
UNION ALL SELECT 'reward_events',             count(*) FROM reward_events
ORDER BY 1;"

echo "==============================================================="
echo " DEV LEDGER RESET  -  DELETES all balances + financial history"
echo "==============================================================="
echo " Target DB : ${DB_ARG}  (local Docker Postgres, via scripts/db.sh)"
echo " Wipes     : ${TABLES}"
echo " Keeps     : accounts, users, tenants, configs, roles, audit_log"
echo " NEVER run this against production - it destroys the ledger."
echo

echo "Row counts BEFORE:"
"$SCRIPT_DIR/db.sh" "$DB_ARG" -c "$COUNT_SQL"
echo

# --- deliberate confirmation (bypass with -y for scripted resets) ------------
if [[ "$ASSUME_YES" -ne 1 ]]; then
  read -r -p "Type RESET to wipe the tables above on '${DB_ARG}': " reply
  if [[ "$reply" != "RESET" ]]; then
    echo "Aborted - nothing changed."
    exit 1
  fi
fi

# One atomic TRUNCATE. RESTART IDENTITY is a no-op here (UUID PKs) but harmless;
# CASCADE resolves FK order and clears any dependent we didn't enumerate.
"$SCRIPT_DIR/db.sh" "$DB_ARG" -c "TRUNCATE ${TABLES} RESTART IDENTITY CASCADE;"

echo
echo "Row counts AFTER:"
"$SCRIPT_DIR/db.sh" "$DB_ARG" -c "$COUNT_SQL"
echo
echo "Done. All wallet balances are now 0 (balance = SUM(ledger_entries) = 0)."
echo "Re-seed opening data if needed:  cd backend && make seed"
