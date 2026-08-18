"""The service codes the platform implements, and which of them are derivable.

Single source of truth for "does a money flow exist for this code". Before
this module the nine codes were scattered — four as module constants
(`CASH_OUT_SERVICE_CODE` and friends) and five as inline string literals —
so nothing could answer that question programmatically. The derived-service
validation in `modules/services/service.py` depends on it, as does the
migration guard that refuses to run against pre-existing dead config.

Deliberately a leaf module: it imports nothing from `app.modules`, so any
module may import it without risking a cycle.
"""

from __future__ import annotations

# A code belongs here only when a module + endpoint actually implement it.
# Adding a code without an implementation reintroduces the dead-config bug
# this registry exists to prevent (spec §1a).
BASE_SERVICE_CODES: frozenset[str] = frozenset(
    {
        "p2p",
        "fund",
        "withdraw",
        "cash_in",
        "cashout",
        "merchant_cashin",
        "airtime_recharge",
        "redemption",
        "change_pin",
    }
)

# `change_pin` moves no money, so it has no fee or limit to differentiate —
# a derived copy of it would be meaningless (spec §3).
NON_DERIVABLE_BASE_CODES: frozenset[str] = frozenset({"change_pin"})

DERIVABLE_BASE_CODES: frozenset[str] = BASE_SERVICE_CODES - NON_DERIVABLE_BASE_CODES

# The flows whose service layer calls `roles.require_permission`, i.e. the only
# codes for which a `role_permissions` grant is a real prerequisite. Verified
# against the call sites: payments (p2p), cashout, cashin, redemption, airtime.
#
# The other four bases deliberately do NOT consult roles, and reporting a
# missing grant for them is a false alarm:
#   - `fund` / `withdraw` are admin-initiated (no end-user role in play);
#   - `merchant_cashin` authenticates a partner by API key, not a user role;
#   - `change_pin` is self-service and not role-gated.
# Keep this in step with the `require_permission` call sites — a code added
# here without an enforcing call site would report a prerequisite nobody
# checks, which is exactly the false alarm this constant exists to stop.
ROLE_ENFORCED_BASE_CODES: frozenset[str] = frozenset(
    {
        "p2p",
        "cashout",
        "cash_in",
        "redemption",
        "airtime_recharge",
    }
)
