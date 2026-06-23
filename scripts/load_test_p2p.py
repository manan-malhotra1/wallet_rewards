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

async def get_admin_token(client: httpx.AsyncClient, args: argparse.Namespace) -> str:
    """Password-grant against the local admin-ui client. Returns a bearer JWT."""
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
    return resp.json()["access_token"]


async def find_tenant_id(
    client: httpx.AsyncClient, api_url: str, name: str, admin_token: str
) -> str:
    """Look up the target tenant by name. Exits if not found."""
    resp = await client.get(
        f"{api_url}/api/v1/tenants",
        headers={"Authorization": f"Bearer {admin_token}"},
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
    admin_token: str,
    tenant_id: str,
    phone: str,
    first_name: str,
    last_name: str,
) -> str:
    """Resolve or create. Returns user_id."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    # Resolve first — cheaper than catching IntegrityError on duplicate create.
    resp = await client.get(
        f"{api_url}/api/v1/identity/resolve/phone/{phone}",
        headers=headers,
        params={"tenant_id": tenant_id},
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json()["user_id"]
    if resp.status_code != 404:
        _fail("identity/resolve", resp)

    create_resp = await client.post(
        f"{api_url}/api/v1/identity/users",
        headers=headers,
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


async def ensure_zar_wallet(
    client: httpx.AsyncClient,
    api_url: str,
    admin_token: str,
    tenant_id: str,
    user_id: str,
) -> None:
    """Create a ZAR financial_wallet for the user if it doesn't exist.

    The accounts endpoint returns 409 on duplicate — we treat that as a no-op.
    """
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        f"{api_url}/api/v1/accounts",
        headers=headers,
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
    admin_token: str,
    tenant_id: str,
    user_id: str,
    desired_pin: str,
) -> str:
    """Admin-reset the PIN. The server picks a random PIN — we then re-reset
    by attempting auth/pin against the returned value and storing the pair.

    Simpler approach since we control the test: use the admin endpoint's
    returned PIN as-is (it varies per user). Caller stores it.
    """
    _ = desired_pin  # honoured by storing the server-generated value; this
    # script never enforces a uniform PIN because pin-reset always randomises.
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.post(
        f"{api_url}/api/v1/identity/users/{user_id}/pin/reset",
        headers=headers,
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
    admin_token: str,
    tenant_id: str,
    phone: str,
    current: float,
    target: float,
) -> None:
    """Top up the user to `target` ZAR via /treasury/fund-user. No-op if already there."""
    diff = target - current
    if diff <= 0:
        return
    resp = await client.post(
        f"{api_url}/api/v1/treasury/fund-user",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "tenant_id": tenant_id,
            "identifier_type": "phone",
            "identifier_value": phone,
            "amount": str(int(diff)),
            "currency": "ZAR",
            "reason": "load-test setup",
        },
        timeout=30,
    )
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Setup orchestrator
# ---------------------------------------------------------------------------

async def setup_users(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    admin_token: str,
    tenant_id: str,
    cache: dict[str, dict],
) -> list[UserSession]:
    """Run phases 3–7 — ensure users / accounts / pins / sessions / funding.

    Reads/writes the state cache so re-runs skip what's already done.
    """
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
                        client, args.api_url, admin_token, tenant_id,
                        phone, bal, args.fund_amount,
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
                client, args.api_url, admin_token, tenant_id,
                phone, f"Load{idx}", "Tester",
            )
            await ensure_zar_wallet(client, args.api_url, admin_token, tenant_id, user_id)
            pin = await set_known_pin(
                client, args.api_url, admin_token, tenant_id, user_id, args.user_pin
            )
            token = await login_pin(client, args.api_url, tenant_id, phone, pin)
            bal = await current_zar_balance(client, args.api_url, token)
            await fund_user_to_target(
                client, args.api_url, admin_token, tenant_id,
                phone, bal, args.fund_amount,
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
        print(
            f"  setup: {chunk_start + len(chunk):>5}/{args.users}  "
            f"(created so far: {created_count}, funded: {funded_count})",
            flush=True,
        )
    return sessions


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
                stats.error_codes[resp.json().get("error_code", f"http_{resp.status_code}")] += 1
            except Exception:
                stats.error_codes[f"http_{resp.status_code}"] += 1
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

def print_summary(args: argparse.Namespace, stats: P2PStats) -> None:
    """Pretty-print the final TPS + latency report."""
    wall = max(time.monotonic() - stats.started_at, 0.001)
    total = stats.success + stats.failure
    print()
    print("=" * 60)
    print("  P2P LOAD TEST — SUMMARY")
    print("=" * 60)
    print(f"  Users participating  : {args.users}")
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
            admin_token = await get_admin_token(client, args)
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
            tenant_id = await find_tenant_id(client, args.api_url, args.tenant_name, admin_token)
            print(f"  + tenant '{args.tenant_name}' = {tenant_id}")

            # Auth smoke test: hit a known-write-protected endpoint (/resolve
            # for a non-existent phone) and assert we get 404, not 401/403.
            # Failure here = setup misconfiguration before we waste time
            # creating users.
            smoke_resp = await client.get(
                f"{args.api_url}/api/v1/identity/resolve/phone/+27 82 999 99999",
                headers={"Authorization": f"Bearer {admin_token}"},
                params={"tenant_id": tenant_id},
                timeout=30,
            )
            if smoke_resp.status_code not in (404, 200):
                _fail("auth smoke test (identity/resolve)", smoke_resp)
            print(f"  + auth smoke test ok (resolve returned {smoke_resp.status_code})")

            print(f"== USERS + ACCOUNTS + PINS + SESSIONS + FUND ({args.users} users) ==")
            sessions = await setup_users(client, args, admin_token, tenant_id, cache)
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
            if "session_token" in entry
        ][: args.users]
        print(f"== P2P (from cache) {len(sessions)} sessions ==")

    if len(sessions) < 2:
        sys.exit("Need at least 2 funded sessions to run P2P. Check setup phase.")

    print(f"== P2P LOAD ({len(sessions)} senders, {args.concurrency} concurrent, "
          f"{args.duration}s) ==")
    stats = await p2p_phase(args, sessions)
    print_summary(args, stats)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
