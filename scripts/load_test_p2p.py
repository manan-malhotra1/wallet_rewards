#!/usr/bin/env python3
"""P2P load test — measures sustained TPS against a running backend.

Phases (idempotent — re-runs skip already-done work):

  1. AUTH      — get a platform-admin Keycloak token via password grant on
                 the local `admin-ui` client.
  2. RESOLVE   — find the target tenant by name.
  3. USERS     — create up to N users (default 5000) with deterministic
                 phone numbers (+27 82 100 00001 .. +27 82 100 05000). Skip
                 any that already resolve.
  4. ACCOUNTS  — create one financial_wallet (ZAR) per user (skip existing).
  5. PINS      — for each new user, admin-reset PIN → known value.
                 Cache (phone, pin) so re-runs skip.
  6. SESSIONS  — POST /auth/pin per user → session_token.
  7. FUND      — top each user up to `--fund-amount` (default R1,000,000).
                 Skip users already at-or-above target.
  8. P2P LOAD  — random sender/recipient pairs, random amount in
                 (--min-amount, --max-amount) ZAR (default R1–R100 to stay
                 below the R200 step-up threshold). Runs for --duration
                 seconds at --concurrency parallel in-flight requests.

Output during P2P phase: every 5 seconds, prints rolling 5s TPS, rolling
30s TPS, success/fail counts. Final summary: total txns, wall-clock
duration, average TPS, error breakdown, latency p50/p95/p99.

Usage (from repo root with backend running):

  cd backend && source .venv/bin/activate
  python ../scripts/load_test_p2p.py --duration 60 --concurrency 50

Re-run with same args to skip setup steps that are already done.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("httpx not installed. Activate backend/.venv first.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse CLI args. All defaults match a stock `make dev` setup."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api-url", default="http://localhost:8000")
    p.add_argument("--keycloak-url", default="http://localhost:8080")
    p.add_argument("--realm", default="wallet-platform")
    p.add_argument("--client-id", default="admin-ui")
    p.add_argument("--client-secret", default="dev-admin-ui-secret-local-only")
    p.add_argument("--admin-user", default="admin-test")
    p.add_argument("--admin-pass", default="admin-test-pass")
    # Treasury funding is a maker-checker money operation: the maker (--admin-user)
    # raises it, a DIFFERENT admin holding `treasury-approver` must approve before
    # any money moves. bootstrap_keycloak.py seeds `admin-approver` for exactly this.
    p.add_argument("--checker-user", default="admin-approver",
                   help="Second admin that approves fund-user money operations.")
    p.add_argument("--checker-pass", default="admin-test-pass")
    p.add_argument("--tenant-name", default="Sasai-ZA")

    p.add_argument("--users", type=int, default=5000, help="Total users to ensure.")
    p.add_argument("--phone-prefix", default="+27 82 100", help="Deterministic phone prefix for load-test users.")
    p.add_argument("--user-pin", default="1234", help="Known PIN set on every load-test user.")
    p.add_argument("--fund-amount", type=int, default=1_000_000, help="Target ZAR balance per user.")

    p.add_argument("--duration", type=int, default=60, help="P2P phase duration (seconds).")
    p.add_argument("--concurrency", type=int, default=50, help="Parallel in-flight P2P requests.")
    p.add_argument("--min-amount", type=int, default=1)
    p.add_argument("--max-amount", type=int, default=100, help="Keep below step-up threshold (R200) to skip PIN re-prompt.")
    p.add_argument("--setup-concurrency", type=int, default=20)

    p.add_argument("--state-file", default="/tmp/sasai_load_test_state.json",
                   help="Cache of created user phones + session tokens for fast re-run.")
    p.add_argument("--phase", choices=["all", "setup", "p2p"], default="all",
                   help="Run setup only, P2P only, or both.")
    return p.parse_args()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class UserSession:
    """One row in the in-memory user cache."""
    phone: str
    user_id: str
    session_token: str
    pin: str = "1234"


@dataclass
class P2PStats:
    """Tally of P2P outcomes for the live + final reports."""
    started_at: float = 0.0
    completed: deque[float] = field(default_factory=lambda: deque(maxlen=200_000))
    latencies_ms: list[float] = field(default_factory=list)
    success: int = 0
    failure: int = 0
    error_codes: Counter[str] = field(default_factory=Counter)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

async def get_admin_token(
    client: httpx.AsyncClient, args: argparse.Namespace
) -> tuple[str, int]:
    """Password-grant against the local admin-ui client.

    Returns:
        (access_token, expires_in_seconds).
    """
    token_url = f"{args.keycloak_url}/realms/{args.realm}/protocol/openid-connect/token"
    resp = await client.post(
        token_url,
        data={
            "grant_type": "password",
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "username": args.admin_user,
            "password": args.admin_pass,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if resp.status_code != 200:
        sys.exit(
            f"Failed to get admin token from {token_url}: "
            f"{resp.status_code} {resp.text}"
        )
    body = resp.json()
    return body["access_token"], int(body.get("expires_in", 300))


class AdminTokenProvider:
    """Holds a Keycloak admin access token and refreshes it before expiry.

    Used by all admin HTTP calls in the script. The setup pass takes
    longer than Keycloak's 5-minute default access-token TTL so a single
    fetched-at-startup token doesn't last the whole run.

    Each .get() returns the current token, transparently re-fetching if
    we're within `safety_window_s` of expiry. Concurrent .get() callers
    serialize on the asyncio.Lock so we never fire two parallel password
    grants.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        args: argparse.Namespace,
        safety_window_s: int = 30,
    ) -> None:
        self.client = client
        self.args = args
        self.safety_window_s = safety_window_s
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()
        self._refresh_count = 0

    async def get(self) -> str:
        """Return a non-stale token (refreshing if needed)."""
        if self._token and time.monotonic() < self._expires_at - self.safety_window_s:
            return self._token
        async with self._lock:
            # Re-check inside the lock so concurrent waiters don't all refresh.
            if self._token and time.monotonic() < self._expires_at - self.safety_window_s:
                return self._token
            token, expires_in = await get_admin_token(self.client, self.args)
            self._token = token
            self._expires_at = time.monotonic() + expires_in
            self._refresh_count += 1
            if self._refresh_count > 1:
                # First fetch is reported by the caller; subsequent refreshes
                # surface here so the operator sees they're happening.
                print(
                    f"  + admin token refreshed (#{self._refresh_count}, "
                    f"expires_in={expires_in}s)",
                    flush=True,
                )
            return token

    async def header(self) -> dict[str, str]:
        """Convenience: build the Authorization header with a fresh token."""
        return {"Authorization": f"Bearer {await self.get()}"}


async def find_tenant_id(
    client: httpx.AsyncClient, api_url: str, name: str, tokens: AdminTokenProvider
) -> str:
    """Look up the target tenant by name. Exits if not found."""
    resp = await client.get(
        f"{api_url}/api/v1/tenants",
        headers=await tokens.header(),
        timeout=30,
    )
    resp.raise_for_status()
    for t in resp.json():
        if t["name"] == name:
            return t["id"]
    sys.exit(f"Tenant '{name}' not found — run seed.py first.")


def phone_for(args: argparse.Namespace, idx: int) -> str:
    """Deterministic phone number for load-test user #idx (1-indexed)."""
    # +27 82 100 NNNNN — last 5 digits zero-padded to match the seed phone format
    # (the backend normalizes whitespace so the exact spacing doesn't matter).
    return f"{args.phone_prefix} {idx:05d}"


# ---------------------------------------------------------------------------
# Setup phase — idempotent ensure-user + account + pin + session
# ---------------------------------------------------------------------------

async def ensure_user(
    client: httpx.AsyncClient,
    api_url: str,
    tokens: AdminTokenProvider,
    tenant_id: str,
    phone: str,
    first_name: str,
    last_name: str,
) -> str:
    """Resolve or create. Returns user_id."""
    # Resolve first — cheaper than catching IntegrityError on duplicate create.
    resp = await client.get(
        f"{api_url}/api/v1/identity/resolve/phone/{phone}",
        headers=await tokens.header(),
        params={"tenant_id": tenant_id},
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json()["user_id"]
    if resp.status_code != 404:
        _fail("identity/resolve", resp)

    create_resp = await client.post(
        f"{api_url}/api/v1/identity/users",
        headers=await tokens.header(),
        json={
            "tenant_id": tenant_id,
            "identifiers": [
                {"identifier_type": "phone", "identifier_value": phone, "verified": True}
            ],
            "profile": {"first_name": first_name, "last_name": last_name},
        },
        timeout=30,
    )
    if create_resp.status_code != 201:
        _fail("identity/users POST", create_resp)
    return create_resp.json()["id"]


def _fail(label: str, resp: httpx.Response) -> None:
    """Raise with status + body so the operator sees the real error_code."""
    body = resp.text[:500] if resp.text else "<empty>"
    raise SystemExit(
        f"\n[{label}] HTTP {resp.status_code} from {resp.request.url}\n"
        f"  request headers:  Authorization=Bearer {resp.request.headers.get('Authorization', '')[:30]}...\n"
        f"  response body:    {body}\n"
    )


async def ensure_permissive_p2p_limit(
    client: httpx.AsyncClient,
    api_url: str,
    tokens: AdminTokenProvider,
    tenant_id: str,
) -> None:
    """Verify the (p2p, financial_wallet, ZAR) limit rows won't strangle the load.

    Historical note: this used to DELETE + re-POST a permissive row, but limit
    mutations moved behind the maker-checker config-requests flow — the direct
    admin API is read-only now (POST/DELETE return 405). Since a load test must
    not silently bypass maker-checker, this step only inspects the live config
    and warns when a rolling cap or amount bound could reject load traffic; the
    operator raises limits through the admin UI's config-requests flow if so.
    """
    list_resp = await client.get(
        f"{api_url}/api/v1/limits/configs",
        headers=await tokens.header(),
        params={"tenant_id": tenant_id},
        timeout=30,
    )
    if list_resp.status_code != 200:
        _fail("limits/configs list", list_resp)

    rows = [
        c
        for c in list_resp.json()
        if c["transaction_type"] == "p2p"
        and c["account_type"] == "financial_wallet"
        and c["currency"] == "ZAR"
    ]
    if not rows:
        # Fail-closed platform: no limit config means every p2p is rejected.
        sys.exit(
            "No p2p limit config exists for this tenant — the platform fails "
            "closed, so every transfer would 422. Seed one (make seed) or add "
            "it via the admin UI config-requests flow, then re-run."
        )

    # Rolling caps small enough to trip during a load run are worth flagging;
    # the thresholds are deliberately loose — this is a smoke warning, not a gate.
    for c in rows:
        cramped = [
            f"{field}={c[field]}"
            for field in (
                "daily_count_cap",
                "daily_value_cap",
                "weekly_count_cap",
                "monthly_count_cap",
            )
            if c.get(field) is not None and float(c[field]) < 100_000
        ]
        if cramped:
            print(
                f"  ! p2p limit row has rolling caps that may trip under load: "
                f"{', '.join(cramped)} — raise via config-requests if the "
                f"error report shows limit rejections."
            )
        if c.get("min_amount") is not None:
            print(
                f"  + p2p per-txn bounds: min={c['min_amount']} "
                f"max={c.get('max_amount')} — keep --min-amount/--max-amount inside them."
            )


async def ensure_load_test_role(
    client: httpx.AsyncClient,
    api_url: str,
    tokens: AdminTokenProvider,
    tenant_id: str,
) -> str:
    """Idempotently ensure a 'load-test-user' role with p2p permission.

    Returns the role_id. Called once per setup pass; the returned id is
    cached and reused for all per-user role assignments.
    """
    list_resp = await client.get(
        f"{api_url}/api/v1/roles",
        headers=await tokens.header(),
        params={"tenant_id": tenant_id},
        timeout=30,
    )
    if list_resp.status_code != 200:
        _fail("roles list", list_resp)
    for role in list_resp.json():
        if role["name"] == "load-test-user":
            return role["id"]

    # Create the role.
    create_resp = await client.post(
        f"{api_url}/api/v1/roles",
        headers=await tokens.header(),
        json={
            "tenant_id": tenant_id,
            "name": "load-test-user",
            "description": "Role used by scripts/load_test_p2p.py — grants p2p.",
        },
        timeout=30,
    )
    if create_resp.status_code != 201:
        _fail("roles create", create_resp)
    role_id: str = create_resp.json()["id"]

    # Grant p2p.
    perm_resp = await client.post(
        f"{api_url}/api/v1/roles/{role_id}/permissions",
        headers=await tokens.header(),
        params={"tenant_id": tenant_id},
        json={"transaction_type": "p2p", "permitted": True},
        timeout=30,
    )
    if perm_resp.status_code != 201:
        _fail("roles permission grant", perm_resp)
    return role_id


async def assign_user_role(
    client: httpx.AsyncClient,
    api_url: str,
    tokens: AdminTokenProvider,
    tenant_id: str,
    user_id: str,
    role_id: str,
) -> None:
    """Assign role_id to user_id. Idempotent — backend returns 201 on re-assign."""
    resp = await client.post(
        f"{api_url}/api/v1/users/{user_id}/roles",
        headers=await tokens.header(),
        params={"tenant_id": tenant_id},
        json={"role_id": role_id},
        timeout=30,
    )
    if resp.status_code != 201:
        _fail("users/{id}/roles POST", resp)


async def ensure_zar_wallet(
    client: httpx.AsyncClient,
    api_url: str,
    tokens: AdminTokenProvider,
    tenant_id: str,
    user_id: str,
) -> None:
    """Create a ZAR financial_wallet for the user if it doesn't exist.

    Robust to partial-state from a previous failed run: we look up the
    user's existing accounts first via /identity/users/{id} and skip
    creation entirely when the ZAR wallet is already there.
    """
    detail_resp = await client.get(
        f"{api_url}/api/v1/identity/users/{user_id}",
        headers=await tokens.header(),
        params={"tenant_id": tenant_id},
        timeout=30,
    )
    if detail_resp.status_code == 200:
        for acct in detail_resp.json().get("accounts", []):
            if (
                acct.get("account_type") == "financial_wallet"
                and acct.get("currency") == "ZAR"
            ):
                return

    resp = await client.post(
        f"{api_url}/api/v1/accounts",
        headers=await tokens.header(),
        json={
            "tenant_id": tenant_id,
            "user_id": user_id,
            "account_type": "financial_wallet",
            "currency": "ZAR",
        },
        timeout=30,
    )
    if resp.status_code in (201, 409):
        return
    _fail("accounts POST", resp)


async def set_known_pin(
    client: httpx.AsyncClient,
    api_url: str,
    tokens: AdminTokenProvider,
    tenant_id: str,
    user_id: str,
    desired_pin: str,
) -> str:
    """Admin-reset the PIN. Returns the server-generated PIN; caller caches it."""
    _ = desired_pin  # script stores the server-generated value (admin reset always randomises)
    resp = await client.post(
        f"{api_url}/api/v1/identity/users/{user_id}/pin/reset",
        headers=await tokens.header(),
        params={"tenant_id": tenant_id},
        timeout=30,
    )
    if resp.status_code != 200:
        _fail("identity/users/{id}/pin/reset", resp)
    body = resp.json()
    new_pin = body.get("new_pin")
    if not new_pin:
        sys.exit(f"pin/reset returned no PIN: {body}")
    return new_pin


async def login_pin(
    client: httpx.AsyncClient,
    api_url: str,
    tenant_id: str,
    phone: str,
    pin: str,
) -> str:
    """Exchange phone+pin for a session_token."""
    resp = await client.post(
        f"{api_url}/api/v1/identity/auth/pin",
        json={"tenant_id": tenant_id, "phone": phone, "pin": pin},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["session_token"]


async def current_zar_balance(
    client: httpx.AsyncClient, api_url: str, session_token: str
) -> float:
    """Read the authenticated user's ZAR balance via /me/wallet."""
    resp = await client.get(
        f"{api_url}/api/v1/identity/me/wallet",
        headers={"Authorization": f"Bearer {session_token}"},
        timeout=30,
    )
    resp.raise_for_status()
    for acct in resp.json()["accounts"]:
        if acct["currency"] == "ZAR" and acct["account_type"] == "financial_wallet":
            return float(acct["balance"])
    return 0.0


async def fund_user_to_target(
    client: httpx.AsyncClient,
    api_url: str,
    tokens: AdminTokenProvider,
    tenant_id: str,
    phone: str,
    current: float,
    target: float,
    checker: AdminTokenProvider | None = None,
) -> None:
    """Top up the user to `target` ZAR via /treasury/fund-user. No-op if already there.

    fund-user is a maker-checker money operation (Epic 18): the 201 only means the
    request was *recorded*, with `status: PENDING` and `applied_transaction_id: null`
    — no money has moved. A second admin holding `treasury-approver` must approve it
    via POST /money-operations/{id}/approve before the ledger is credited.

    Treating the 201 as "funded" is why an earlier version of this script left every
    freshly-created user at a zero balance, turning the whole P2P phase into a wall of
    `insufficient_funds`. So we drive the approval here and assert the terminal state
    is APPLIED, failing loudly rather than silently under-provisioning.

    This completes maker-checker with the seeded second dev admin; it does not bypass
    it (self-approval is rejected server-side with `self_approval_forbidden`).
    """
    diff = target - current
    # Truncate FIRST, then decide. Fees and taxes leave fractional balances
    # (a 0.525 tax makes a balance like 199_999.475), so a sub-unit shortfall
    # truncates to "0" — which fund-user rejects with a 422 `greater_than`.
    # A shortfall under R1 means already-funded for a coarse top-up target.
    whole_amount = int(diff)
    if whole_amount <= 0:
        return
    resp = await client.post(
        f"{api_url}/api/v1/treasury/fund-user",
        headers=await tokens.header(),
        json={
            "tenant_id": tenant_id,
            "identifier_type": "phone",
            "identifier_value": phone,
            "amount": str(whole_amount),
            "currency": "ZAR",
            "reason": "load-test setup",
        },
        timeout=30,
    )
    if resp.status_code != 201:
        _fail("treasury/fund-user", resp)

    body = resp.json()
    status = body.get("status")
    if status == "APPLIED":
        return  # Tenant has approvals disabled — money already moved.
    if status != "PENDING":
        raise SystemExit(
            f"\n[treasury/fund-user] unexpected money-op status {status!r} for {phone} "
            f"(expected PENDING or APPLIED). Body: {json.dumps(body)[:400]}"
        )
    if checker is None:
        raise SystemExit(
            f"\n[treasury/fund-user] {phone} funding is PENDING maker-checker approval "
            f"but no checker token provider was supplied — users would be left unfunded."
        )

    request_id = body["id"]
    appr = await client.post(
        f"{api_url}/api/v1/money-operations/{request_id}/approve",
        headers=await checker.header(),
        params={"tenant_id": tenant_id},
        json={"comment": "load-test setup funding"},
        timeout=30,
    )
    if appr.status_code != 200:
        _fail("money-operations/approve", appr)
    final = appr.json().get("status")
    if final != "APPLIED":
        # e.g. required_approvals > 1 — the load test cannot proceed unfunded.
        raise SystemExit(
            f"\n[money-operations/approve] {phone} money-op ended {final!r}, not APPLIED "
            f"(approvals {appr.json().get('approvals_count')}/"
            f"{appr.json().get('required_approvals')}). Body: {json.dumps(appr.json())[:400]}"
        )


# ---------------------------------------------------------------------------
# Setup orchestrator
# ---------------------------------------------------------------------------

async def setup_users(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    tokens: AdminTokenProvider,
    tenant_id: str,
    cache: dict[str, dict],
    checker: AdminTokenProvider | None = None,
) -> list[UserSession]:
    """Run phases 3–7 — ensure users / accounts / pins / roles / sessions / funding.

    Reads/writes the state cache so re-runs skip what's already done.
    State is checkpointed after every batch so a mid-run crash doesn't
    lose progress.
    """
    # One-time: ensure permissive p2p limits + load-test role exist.
    await ensure_permissive_p2p_limit(client, args.api_url, tokens, tenant_id)
    print("  + permissive p2p limits ensured")
    role_id = await ensure_load_test_role(client, args.api_url, tokens, tenant_id)
    print(f"  + load-test role ready ({role_id[:8]}…)")

    sessions: list[UserSession] = []
    sem = asyncio.Semaphore(args.setup_concurrency)
    created_count = 0
    funded_count = 0

    async def ensure_one(idx: int) -> UserSession:
        nonlocal created_count, funded_count
        async with sem:
            phone = phone_for(args, idx)
            cached = cache.get(phone)

            if cached and "session_token" in cached:
                # Verify token still valid by hitting /me/wallet — cheap call.
                try:
                    bal = await current_zar_balance(client, args.api_url, cached["session_token"])
                    if bal >= args.fund_amount:
                        return UserSession(
                            phone=phone,
                            user_id=cached["user_id"],
                            session_token=cached["session_token"],
                            pin=cached.get("pin", args.user_pin),
                        )
                    # Token still valid; just needs more funding.
                    await fund_user_to_target(
                        client, args.api_url, tokens, tenant_id,
                        phone, bal, args.fund_amount, checker,
                    )
                    funded_count += 1
                    return UserSession(
                        phone=phone,
                        user_id=cached["user_id"],
                        session_token=cached["session_token"],
                        pin=cached.get("pin", args.user_pin),
                    )
                except httpx.HTTPStatusError:
                    pass  # Token expired — fall through to full re-setup.

            user_id = await ensure_user(
                client, args.api_url, tokens, tenant_id,
                phone, f"Load{idx}", "Tester",
            )
            await ensure_zar_wallet(client, args.api_url, tokens, tenant_id, user_id)
            await assign_user_role(
                client, args.api_url, tokens, tenant_id, user_id, role_id
            )
            pin = await set_known_pin(
                client, args.api_url, tokens, tenant_id, user_id, args.user_pin
            )
            token = await login_pin(client, args.api_url, tenant_id, phone, pin)
            bal = await current_zar_balance(client, args.api_url, token)
            await fund_user_to_target(
                client, args.api_url, tokens, tenant_id,
                phone, bal, args.fund_amount, checker,
            )
            created_count += 1
            funded_count += 1
            cache[phone] = {"user_id": user_id, "session_token": token, "pin": pin}
            return UserSession(phone=phone, user_id=user_id, session_token=token, pin=pin)

    # Run setup in batches so a 5000-user pass logs progress.
    tasks = [ensure_one(i + 1) for i in range(args.users)]
    batch_size = 500
    for chunk_start in range(0, len(tasks), batch_size):
        chunk = tasks[chunk_start:chunk_start + batch_size]
        sessions.extend(await asyncio.gather(*chunk))
        # Checkpoint after every batch so a mid-run crash doesn't lose progress.
        save_state(args.state_file, cache)
        print(
            f"  setup: {chunk_start + len(chunk):>5}/{args.users}  "
            f"(created so far: {created_count}, funded: {funded_count}, "
            f"cache checkpointed)",
            flush=True,
        )
    return sessions


async def refresh_all_sessions(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    cache: dict[str, dict],
    sessions: list[UserSession],
) -> None:
    """Re-login every user with their cached PIN and overwrite the session token.

    Run before each P2P phase because user sessions expire after 15 min
    (backend SESSION_TTL_SECONDS) and the cache may be older. PINs in the
    cache survive — they're set on the user row, not in Redis — so a
    fresh login_pin gets us a fresh token without re-running PIN reset.

    Mutates `sessions` and `cache` in place. Tenant id is parsed from the
    first session's user_id... actually pulled from the first cache entry
    via a side query — cleanest: pass it through.
    """
    # Tenant lookup. We need it for the auth/pin body.
    # The cached entries don't carry tenant_id explicitly, so look it up.
    tokens = AdminTokenProvider(client, args)
    tenant_id = await find_tenant_id(client, args.api_url, args.tenant_name, tokens)

    sem = asyncio.Semaphore(args.setup_concurrency)
    refreshed = 0
    failed = 0
    failures: list[str] = []

    async def refresh_one(s: UserSession) -> None:
        nonlocal refreshed, failed
        async with sem:
            try:
                new_token = await login_pin(
                    client, args.api_url, tenant_id, s.phone, s.pin
                )
                s.session_token = new_token
                cache[s.phone]["session_token"] = new_token
                refreshed += 1
            except httpx.HTTPStatusError as exc:
                failed += 1
                if len(failures) < 3:
                    body = exc.response.text[:200] if exc.response else "<no resp>"
                    failures.append(f"{s.phone}: {exc.response.status_code} {body}")

    tasks = [refresh_one(s) for s in sessions]
    batch_size = 500
    for chunk_start in range(0, len(tasks), batch_size):
        chunk = tasks[chunk_start:chunk_start + batch_size]
        await asyncio.gather(*chunk)
        print(
            f"  refresh: {min(chunk_start + len(chunk), len(tasks)):>5}/{len(tasks)}  "
            f"(ok={refreshed}, failed={failed})",
            flush=True,
        )
    for line in failures:
        print(f"  ! login failure: {line}")


def load_state(path: str) -> dict[str, dict]:
    """Load the cached (phone -> {user_id, session_token, pin}) map."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(path: str, cache: dict[str, dict]) -> None:
    """Write the cache atomically (tmp+rename)."""
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.replace(p)


# ---------------------------------------------------------------------------
# P2P load phase
# ---------------------------------------------------------------------------

async def one_p2p(
    client: httpx.AsyncClient,
    api_url: str,
    sender: UserSession,
    recipient: UserSession,
    amount: int,
    stats: P2PStats,
) -> None:
    """Fire a single P2P transfer; update stats."""
    t0 = time.monotonic()
    try:
        resp = await client.post(
            f"{api_url}/api/v1/payments/p2p",
            headers={
                "Authorization": f"Bearer {sender.session_token}",
                "Idempotency-Key": uuid.uuid4().hex,
            },
            json={
                "recipient": {
                    "identifier_type": "phone",
                    "identifier_value": recipient.phone,
                },
                "amount": str(amount),
                "currency": "ZAR",
            },
            timeout=30,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        stats.latencies_ms.append(elapsed_ms)
        stats.completed.append(time.monotonic())
        if 200 <= resp.status_code < 300:
            stats.success += 1
        else:
            stats.failure += 1
            try:
                code = resp.json().get("error_code", f"http_{resp.status_code}")
            except Exception:
                code = f"http_{resp.status_code}"
            stats.error_codes[code] += 1
            # Log the first 3 details for each error code — helps diagnose
            # opaque 500s without spamming the console.
            if stats.error_codes[code] <= 3:
                body = resp.text[:200] if resp.text else "<empty>"
                print(
                    f"  ! {code}: sender={sender.phone} → {recipient.phone} "
                    f"amount={amount} body={body}",
                    flush=True,
                )
    except httpx.HTTPError as exc:
        stats.failure += 1
        stats.error_codes[type(exc).__name__] += 1


async def reporter(stats: P2PStats, duration: int) -> None:
    """Print rolling TPS every 5 seconds while the P2P phase runs."""
    last_completed = 0
    while True:
        await asyncio.sleep(5)
        now = time.monotonic()
        elapsed = now - stats.started_at
        if elapsed >= duration:
            return
        cum = stats.success + stats.failure
        delta = cum - last_completed
        last_completed = cum
        # Rolling 5s TPS — interval count divided by 5s.
        tps_5s = delta / 5
        # Rolling 30s TPS — count completions in last 30s from the deque.
        cutoff = now - 30
        recent = sum(1 for ts in stats.completed if ts >= cutoff)
        tps_30s = recent / min(30, elapsed)
        print(
            f"  t={elapsed:>5.1f}s  total={cum:>7}  "
            f"5s={tps_5s:>7.1f}/s  30s={tps_30s:>7.1f}/s  "
            f"ok={stats.success}  fail={stats.failure}",
            flush=True,
        )


async def p2p_phase(
    args: argparse.Namespace,
    sessions: list[UserSession],
) -> P2PStats:
    """Run the P2P load for --duration seconds. Returns aggregated stats."""
    stats = P2PStats()
    stats.started_at = time.monotonic()
    end_at = stats.started_at + args.duration

    limits = httpx.Limits(
        max_connections=args.concurrency * 2,
        max_keepalive_connections=args.concurrency * 2,
    )
    async with httpx.AsyncClient(limits=limits, timeout=30) as client:
        # Live progress in the background.
        reporter_task = asyncio.create_task(reporter(stats, args.duration))

        sem = asyncio.Semaphore(args.concurrency)
        rnd = random.Random(42)

        async def driver() -> None:
            async with sem:
                sender = rnd.choice(sessions)
                # Pick a different recipient.
                while True:
                    recipient = rnd.choice(sessions)
                    if recipient.user_id != sender.user_id:
                        break
                amount = rnd.randint(args.min_amount, args.max_amount)
                await one_p2p(client, args.api_url, sender, recipient, amount, stats)

        # Fire-and-track loop — keep spawning tasks until duration runs out.
        active: set[asyncio.Task] = set()
        try:
            while time.monotonic() < end_at:
                if len(active) < args.concurrency * 2:
                    t = asyncio.create_task(driver())
                    active.add(t)
                    t.add_done_callback(active.discard)
                else:
                    # Wait for at least one to finish before spawning more.
                    await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
            # Drain in-flight.
            if active:
                await asyncio.gather(*active, return_exceptions=True)
        finally:
            reporter_task.cancel()
            try:
                await reporter_task
            except asyncio.CancelledError:
                pass

    return stats


# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------

def print_summary(args: argparse.Namespace, stats: P2PStats, n_sessions: int) -> None:
    """Pretty-print the final TPS + latency report."""
    wall = max(time.monotonic() - stats.started_at, 0.001)
    total = stats.success + stats.failure
    print()
    print("=" * 60)
    print("  P2P LOAD TEST — SUMMARY")
    print("=" * 60)
    print(f"  Users participating  : {n_sessions}")
    print(f"  Concurrency          : {args.concurrency}")
    print(f"  Duration target      : {args.duration}s")
    print(f"  Wall clock           : {wall:.2f}s")
    print(f"  Requests total       : {total}")
    print(f"  Successful           : {stats.success}")
    print(f"  Failed               : {stats.failure}")
    avg_tps = total / wall if wall > 0 else 0
    ok_tps = stats.success / wall if wall > 0 else 0
    print(f"  Average TPS (all)    : {avg_tps:.1f}")
    print(f"  Average TPS (ok)     : {ok_tps:.1f}")
    if stats.latencies_ms:
        ls = sorted(stats.latencies_ms)
        def pct(p: float) -> float:
            return ls[min(len(ls) - 1, int(len(ls) * p / 100))]
        print(f"  Latency p50          : {pct(50):.1f} ms")
        print(f"  Latency p95          : {pct(95):.1f} ms")
        print(f"  Latency p99          : {pct(99):.1f} ms")
        print(f"  Latency mean         : {statistics.fmean(ls):.1f} ms")
    if stats.error_codes:
        print("  Errors by code       :")
        for code, n in stats.error_codes.most_common():
            print(f"    {code:30s} {n}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    """Entry point — wires setup + P2P phases together."""
    args = parse_args()
    print(f"Load test against {args.api_url}")
    print(f"Target: {args.users} users, {args.fund_amount} ZAR each, "
          f"P2P amounts R{args.min_amount}-R{args.max_amount} for {args.duration}s "
          f"at concurrency {args.concurrency}.")

    cache = load_state(args.state_file)
    sessions: list[UserSession] = []

    if args.phase in ("all", "setup"):
        async with httpx.AsyncClient(timeout=30) as client:
            print("== AUTH ==")
            tokens = AdminTokenProvider(client, args)
            admin_token = await tokens.get()
            print(f"  + admin token acquired ({len(admin_token)} chars)")

            # Decode the JWT payload (no signature check) to confirm roles.
            # This catches the "token works on lenient endpoints but lacks
            # platform-admin role for write endpoints" misconfiguration up front.
            import base64
            try:
                _hdr, payload_b64, _sig = admin_token.split(".")
                payload_b64 += "=" * (-len(payload_b64) % 4)
                claims = json.loads(base64.urlsafe_b64decode(payload_b64))
                roles = claims.get("realm_access", {}).get("roles", [])
                username = claims.get("preferred_username", "<unknown>")
                aud = claims.get("aud", "<no-aud>")
                iss = claims.get("iss", "<no-iss>")
                print(f"  + token claims: user={username}, iss={iss}")
                print(f"  + token claims: aud={aud}")
                print(f"  + token claims: realm_access.roles={roles}")
                if "platform-admin" not in roles:
                    sys.exit(
                        "\nFATAL: token does NOT contain the 'platform-admin' role.\n"
                        "Run: python scripts/bootstrap_keycloak.py\n"
                        "Then verify in Keycloak admin UI that user 'admin-test'\n"
                        "has the 'platform-admin' realm role assigned.\n"
                    )
            except (ValueError, json.JSONDecodeError):
                print("  ! could not decode JWT payload (continuing)")

            print("== TENANT ==")
            tenant_id = await find_tenant_id(client, args.api_url, args.tenant_name, tokens)
            print(f"  + tenant '{args.tenant_name}' = {tenant_id}")

            # Auth smoke test: hit a known-write-protected endpoint (/resolve
            # for a non-existent phone) and assert we get 404, not 401/403.
            # Failure here = setup misconfiguration before we waste time
            # creating users.
            smoke_resp = await client.get(
                f"{args.api_url}/api/v1/identity/resolve/phone/+27 82 999 99999",
                headers=await tokens.header(),
                params={"tenant_id": tenant_id},
                timeout=30,
            )
            if smoke_resp.status_code not in (404, 200):
                _fail("auth smoke test (identity/resolve)", smoke_resp)
            print(f"  + auth smoke test ok (resolve returned {smoke_resp.status_code})")

            # Second admin for the maker-checker money-op approvals. Same client_id /
            # secret, different user — the server rejects self-approval.
            checker_args = argparse.Namespace(**{
                **vars(args),
                "admin_user": args.checker_user,
                "admin_pass": args.checker_pass,
            })
            checker = AdminTokenProvider(client, checker_args)
            await checker.get()
            print(f"  + checker token acquired (user={args.checker_user})")

            print(f"== USERS + ACCOUNTS + PINS + SESSIONS + FUND ({args.users} users) ==")
            sessions = await setup_users(client, args, tokens, tenant_id, cache, checker)
            save_state(args.state_file, cache)
            print(f"  + setup complete. State cached at {args.state_file}")

    if args.phase == "setup":
        print("setup-only mode: stopping before P2P phase.")
        return

    # Rebuild sessions from cache when --phase=p2p.
    if not sessions:
        if not cache:
            sys.exit("No cached sessions — run setup first (--phase setup).")
        sessions = [
            UserSession(
                phone=phone,
                user_id=entry["user_id"],
                session_token=entry["session_token"],
                pin=entry.get("pin", args.user_pin),
            )
            for phone, entry in cache.items()
            if "session_token" in entry and "pin" in entry
        ][: args.users]
        print(f"== P2P (from cache) {len(sessions)} sessions ==")

        # Refresh sessions before P2P. SESSION_TTL_SECONDS in the backend is
        # 15 minutes — any cached token older than that is dead. We always
        # re-login on a p2p-only run because we can't tell whether a token
        # is still alive without probing it (and a wasted P2P with an
        # expired token is a worse outcome than spending 30-60s here).
        async with httpx.AsyncClient(timeout=30) as client:
            print(f"== REFRESH SESSIONS ({len(sessions)} users) ==")
            await refresh_all_sessions(client, args, cache, sessions)
            save_state(args.state_file, cache)
            print(f"  + sessions refreshed. State cached at {args.state_file}")

    if len(sessions) < 2:
        sys.exit("Need at least 2 funded sessions to run P2P. Check setup phase.")

    print(f"== P2P LOAD ({len(sessions)} senders, {args.concurrency} concurrent, "
          f"{args.duration}s) ==")
    stats = await p2p_phase(args, sessions)
    print_summary(args, stats, len(sessions))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
