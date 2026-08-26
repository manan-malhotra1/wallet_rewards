#!/usr/bin/env python3
"""Consolidated multi-service load test — mixes every money-movement service.

Where `load_test_p2p.py` drives one endpoint, this drives the whole money surface
at once, in one weighted stream, and reports per-service throughput/latency:

  p2p              consumer -> consumer   POST /payments/p2p
  cashout          consumer -> agent      POST /cashout
  airtime          consumer -> MNO        POST /airtime/recharge     (simulator provider)
  cash_in          agent    -> consumer   POST /cashin
  merchant_cashin  merchant -> consumer   POST /external/merchant-cashin  (API key + HMAC)

Setup helpers (auth, users, wallets, PINs, sessions, funding) are imported from
`load_test_p2p` so the maker-checker funding fix lives in exactly one place.

WHAT THE PLATFORM MAKES YOU GET RIGHT (each of these silently breaks a naive run):

  * Typed users. `cash_in` is only permitted to `agent`/`super_agent` and
    `merchant_cashin` to `merchant`/`head_merchant` (services.allowed_user_types).
    An `agent` needs a `super_agent` parent and a `merchant` a `head_merchant`
    parent (PARENT_TYPE_BY_CHILD), so this script builds both chains.
  * Role permissions. `require_permission` gates every service, and the
    `load-test-user` role historically granted p2p ONLY — cashout and
    airtime_recharge 403 until granted. Done in `ensure_permissions`.
  * Cash-out direction. A subscriber cashes out TO AN AGENT; passing the
    caller's own identifier is `self_transfer_not_allowed`, and a non-agent
    recipient is `recipient_not_agent`.
  * Agent/merchant float. cash_in debits the AGENT's own wallet and
    merchant_cashin the MERCHANT's, so both pools need funding, not just consumers.
  * Step-up. Policies trigger PIN re-verification above R200 for p2p, cashout,
    cash_in and airtime. Amounts are held under it by default: a step-up prompt
    would measure PIN hashing (deliberately slow) rather than the money path.
  * Airtime simulator. msisdn suffix `0001` forces `failed` and `0002` forces
    `pending`; both are avoided so a red line means a real regression.
  * API-key rate limit. The external API allows API_KEY_RATE_LIMIT (60) requests
    per 60s PER KEY, so merchant_cashin is ~1 TPS per key. `--merchant-keys`
    mints several and round-robins to buy headroom; 429s are reported separately.

Prerequisites: infra + backend up, DB seeded, `bootstrap_keycloak.py` run (it
seeds the `admin-approver` checker). The seeded `merchant_cashin` limit row caps
the service at 1 txn/day/merchant — raise it through the config-requests flow
first or that leg will 429 immediately.

Usage:
  backend/.venv/bin/python scripts/load_test_mixed.py --duration 60 --concurrency 50
  ... --weights p2p=40,cashout=20,airtime=20,cash_in=15,merchant_cashin=5
  ... --phase setup          # provision only
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import random
import statistics
import sys
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_test_p2p as L  # shared setup helpers

SERVICES = ("p2p", "cashout", "airtime", "cash_in", "merchant_cashin")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--api-url", default="http://localhost:8000")
    p.add_argument("--keycloak-url", default="http://localhost:8080")
    p.add_argument("--realm", default="wallet-platform")
    p.add_argument("--client-id", default="admin-ui")
    p.add_argument("--client-secret", default="dev-admin-ui-secret-local-only")
    p.add_argument("--admin-user", default="admin-test")
    p.add_argument("--admin-pass", default="admin-test-pass")
    p.add_argument("--checker-user", default="admin-approver",
                   help="Second admin that approves fund-user money operations.")
    p.add_argument("--checker-pass", default="admin-test-pass")
    p.add_argument("--tenant-name", default="Sasai-ZA")

    p.add_argument("--users", type=int, default=500, help="Consumer pool size.")
    p.add_argument("--agents", type=int, default=10, help="Agent pool (cash_in payers / cashout payees).")
    p.add_argument("--merchant-keys", type=int, default=10,
                   help="API keys minted for merchant_cashin (60 req/min each).")
    p.add_argument("--phone-prefix", default="+27 82 100")
    p.add_argument("--agent-prefix", default="+27 86 200")
    p.add_argument("--user-pin", default="1234")
    p.add_argument("--fund-amount", type=int, default=10_000, help="Target ZAR per consumer.")
    p.add_argument("--agent-fund-amount", type=int, default=200_000,
                   help="Target ZAR per agent.")
    p.add_argument("--merchant-fund-amount", type=int, default=2_000_000,
                   help="Target ZAR for the merchant.")

    p.add_argument("--duration", type=int, default=60)
    p.add_argument("--concurrency", type=int, default=50)
    p.add_argument("--min-amount", type=int, default=5,
                   help="Above every service's min (p2p/cashout/airtime/cash_in = R5).")
    p.add_argument("--max-amount", type=int, default=100,
                   help="Below the R200 step-up threshold.")
    p.add_argument("--weights",
                   default="p2p=40,cashout=20,airtime=20,cash_in=15,merchant_cashin=5",
                   help="Comma-separated service=weight mix.")
    p.add_argument("--no-fund", action="store_true",
                   help="Never call treasury/fund-user — transact purely off existing "
                        "balances. Insufficient balance then surfaces as a real "
                        "`insufficient_funds` result instead of being papered over.")
    p.add_argument("--setup-concurrency", type=int, default=40)
    p.add_argument("--state-file", default="/tmp/sasai_load_test_state.json",
                   help="Consumer cache — shared with load_test_p2p.py.")
    p.add_argument("--mixed-state-file", default="/tmp/sasai_load_test_mixed_state.json",
                   help="Agent / merchant / API-key cache for this script.")
    p.add_argument("--phase", choices=["all", "setup", "load"], default="all")
    return p.parse_args()


def parse_weights(spec: str) -> dict[str, int]:
    """Turn `p2p=40,cashout=20,...` into a validated weight map."""
    weights: dict[str, int] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            sys.exit(f"--weights entry {part!r} is not service=weight")
        name, _, raw = part.partition("=")
        name = name.strip()
        if name not in SERVICES:
            sys.exit(f"--weights unknown service {name!r}; pick from {', '.join(SERVICES)}")
        try:
            weights[name] = int(raw)
        except ValueError:
            sys.exit(f"--weights weight for {name!r} is not an integer: {raw!r}")
    live = {k: v for k, v in weights.items() if v > 0}
    if not live:
        sys.exit("--weights must leave at least one service with a positive weight")
    return live


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class Actor:
    """A provisioned user we can transact as."""
    phone: str
    user_id: str
    session_token: str
    pin: str


@dataclass
class ServiceStats:
    """Per-service tally."""
    success: int = 0
    failure: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    error_codes: Counter[str] = field(default_factory=Counter)


@dataclass
class MixedStats:
    """Whole-run tally, sliced per service."""
    started_at: float = 0.0
    completed: deque[float] = field(default_factory=lambda: deque(maxlen=200_000))
    per_service: dict[str, ServiceStats] = field(
        default_factory=lambda: {s: ServiceStats() for s in SERVICES}
    )

    @property
    def success(self) -> int:
        return sum(s.success for s in self.per_service.values())

    @property
    def failure(self) -> int:
        return sum(s.failure for s in self.per_service.values())

    def record(self, service: str, ok: bool, elapsed_ms: float, code: str | None) -> None:
        st = self.per_service[service]
        st.latencies_ms.append(elapsed_ms)
        self.completed.append(time.monotonic())
        if ok:
            st.success += 1
        else:
            st.failure += 1
            st.error_codes[code or "unknown"] += 1


def sign_body(raw_body: bytes, secret: str, timestamp: int | None = None) -> str:
    """Build an X-Sasai-Signature value: t=<unix>,v1=hex(HMAC_SHA256(secret,"{t}.{body}")).

    Mirrors app.auth.hmac.build_signature_header. Reimplemented rather than
    imported because importing app.auth pulls in app.config, which instantiates
    Settings() and needs the backend .env resolvable from the CWD.
    """
    ts = int(timestamp if timestamp is not None else time.time())
    canonical = f"{ts}.".encode() + raw_body
    return f"t={ts},v1={hmac.new(secret.encode('utf-8'), canonical, sha256).hexdigest()}"


def load_json(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=1))


# ---------------------------------------------------------------------------
# Setup — roles, typed-user chains, funding, API keys
# ---------------------------------------------------------------------------

async def ensure_role(
    client: httpx.AsyncClient, args: argparse.Namespace, tokens: L.AdminTokenProvider,
    tenant_id: str, name: str, description: str, permissions: tuple[str, ...],
) -> str:
    """Idempotently ensure a role exists and grants every listed service.

    Permissions are re-granted on every run: the role may pre-date this script
    (the p2p harness creates `load-test-user` with p2p only) and a missing grant
    surfaces as an opaque 403 mid-load.
    """
    resp = await client.get(f"{args.api_url}/api/v1/roles",
                            headers=await tokens.header(),
                            params={"tenant_id": tenant_id}, timeout=30)
    if resp.status_code != 200:
        L._fail("roles list", resp)

    role_id = next((r["id"] for r in resp.json() if r["name"] == name), None)
    if role_id is None:
        create = await client.post(f"{args.api_url}/api/v1/roles",
            headers=await tokens.header(),
            json={"tenant_id": tenant_id, "name": name, "description": description},
            timeout=30)
        if create.status_code != 201:
            L._fail("roles create", create)
        role_id = create.json()["id"]

    for txn in permissions:
        grant = await client.post(f"{args.api_url}/api/v1/roles/{role_id}/permissions",
            headers=await tokens.header(), params={"tenant_id": tenant_id},
            json={"transaction_type": txn, "permitted": True}, timeout=30)
        # 200 (updated) and 201 (created) are both fine; anything else is fatal.
        if grant.status_code not in (200, 201):
            L._fail(f"roles permission grant ({txn})", grant)
    return role_id


async def ensure_typed_user(
    client: httpx.AsyncClient, args: argparse.Namespace, tokens: L.AdminTokenProvider,
    tenant_id: str, phone: str, first_name: str, user_type: str,
    parent_user_id: str | None = None,
) -> str:
    """Resolve-or-create a user of `user_type`. Returns user_id.

    Resolve first: create-on-existing is a duplicate-identifier 409, and re-runs
    are expected to be idempotent.
    """
    resolve = await client.get(f"{args.api_url}/api/v1/identity/resolve/phone/{phone}",
        headers=await tokens.header(), params={"tenant_id": tenant_id}, timeout=30)
    if resolve.status_code == 200:
        return resolve.json()["user_id"]
    if resolve.status_code != 404:
        L._fail("identity/resolve", resolve)

    body: dict = {
        "tenant_id": tenant_id,
        "identifiers": [{"identifier_type": "phone", "identifier_value": phone, "verified": True}],
        "profile": {"first_name": first_name, "last_name": "LoadTest"},
        "user_type": user_type,
    }
    if parent_user_id:
        body["parent_user_id"] = parent_user_id
    create = await client.post(f"{args.api_url}/api/v1/identity/users",
                               headers=await tokens.header(), json=body, timeout=30)
    if create.status_code != 201:
        L._fail(f"identity/users POST ({user_type})", create)
    return create.json()["id"]


async def provision_actor(
    client: httpx.AsyncClient, args: argparse.Namespace, tokens: L.AdminTokenProvider,
    checker: L.AdminTokenProvider, tenant_id: str, phone: str, user_id: str,
    role_id: str | None, target_balance: int,
) -> Actor:
    """Give a user a ZAR wallet, role, known PIN, live session and (unless
    --no-fund) funding up to `target_balance`."""
    await L.ensure_zar_wallet(client, args.api_url, tokens, tenant_id, user_id)
    if role_id:
        await L.assign_user_role(client, args.api_url, tokens, tenant_id, user_id, role_id)
    # The admin reset RANDOMISES the PIN and returns it — the requested value is
    # ignored, so we must authenticate with whatever comes back.
    pin = await L.set_known_pin(client, args.api_url, tokens, tenant_id, user_id, args.user_pin)
    token = await L.login_pin(client, args.api_url, tenant_id, phone, pin)
    if not args.no_fund:
        balance = await L.current_zar_balance(client, args.api_url, token)
        await L.fund_user_to_target(client, args.api_url, tokens, tenant_id,
                                    phone, balance, target_balance, checker)
    return Actor(phone=phone, user_id=user_id, session_token=token, pin=pin)


async def setup_consumers(
    client: httpx.AsyncClient, args: argparse.Namespace, tokens: L.AdminTokenProvider,
    checker: L.AdminTokenProvider, tenant_id: str, role_id: str, cache: dict,
) -> list[Actor]:
    """Provision the consumer pool, reusing the p2p script's state cache."""
    sem = asyncio.Semaphore(args.setup_concurrency)
    created = 0

    async def one(idx: int) -> Actor:
        nonlocal created
        async with sem:
            phone = f"{args.phone_prefix} {idx:05d}"
            entry = cache.get(phone)
            if entry and "session_token" in entry:
                # Cheapest possible liveness probe on the cached session.
                try:
                    balance = await L.current_zar_balance(client, args.api_url, entry["session_token"])
                    if not args.no_fund and balance < args.fund_amount:
                        await L.fund_user_to_target(client, args.api_url, tokens, tenant_id,
                                                    phone, balance, args.fund_amount, checker)
                    return Actor(phone=phone, user_id=entry["user_id"],
                                 session_token=entry["session_token"],
                                 pin=entry.get("pin", args.user_pin))
                except httpx.HTTPStatusError:
                    pass  # Token expired — fall through to a full re-provision.

            user_id = await L.ensure_user(client, args.api_url, tokens, tenant_id,
                                          phone, f"Load{idx}", "Tester")
            actor = await provision_actor(client, args, tokens, checker, tenant_id,
                                          phone, user_id, role_id, args.fund_amount)
            created += 1
            cache[phone] = {"user_id": actor.user_id, "session_token": actor.session_token,
                            "pin": actor.pin}
            return actor

    actors: list[Actor] = []
    tasks = [one(i + 1) for i in range(args.users)]
    for start in range(0, len(tasks), 500):
        actors.extend(await asyncio.gather(*tasks[start:start + 500]))
        save_json(args.state_file, cache)
        print(f"  consumers: {min(start + 500, len(tasks)):>5}/{args.users} "
              f"(newly provisioned: {created})", flush=True)
    return actors


async def setup_agents(
    client: httpx.AsyncClient, args: argparse.Namespace, tokens: L.AdminTokenProvider,
    checker: L.AdminTokenProvider, tenant_id: str, cache: dict,
) -> list[Actor]:
    """Provision one super_agent parent plus the agent pool.

    Agents both PAY (cash_in debits their own float) and RECEIVE (cashout credits
    them), so they are funded above the consumer target.

    Batched + checkpointed + cache-reusing, like the consumer pool, because agent
    provisioning is the most expensive setup there is: each new agent costs two
    bcrypt rounds (PIN reset hashes, PIN login verifies) on a CPU-bound single
    process, plus a fund + approve money-op pair. At pool sizes in the hundreds
    that is minutes of work, so losing it all to one late failure — or redoing it
    on every re-run — is what makes a large-pool test impractical.
    """
    agent_role = await ensure_role(client, args, tokens, tenant_id, "load-test-agent",
                                   "Role used by load_test_mixed.py — grants cash_in.",
                                   ("cash_in",))
    super_phone = "+27 86 100 00001"
    super_id = await ensure_typed_user(client, args, tokens, tenant_id,
                                       super_phone, "SuperAgent", "super_agent")
    print(f"  + super_agent ready ({super_id[:8]}…)")

    agent_cache = cache.setdefault("agents", {})
    sem = asyncio.Semaphore(args.setup_concurrency)
    provisioned = 0

    async def one(idx: int) -> Actor:
        nonlocal provisioned
        async with sem:
            phone = f"{args.agent_prefix} {idx:05d}"
            entry = agent_cache.get(phone)
            if entry and "session_token" in entry:
                # A live cached session skips both bcrypt rounds — the whole point
                # of the cache. Top up only if the float has drained below target.
                try:
                    balance = await L.current_zar_balance(client, args.api_url,
                                                          entry["session_token"])
                    if not args.no_fund and balance < args.agent_fund_amount:
                        await L.fund_user_to_target(
                            client, args.api_url, tokens, tenant_id, phone,
                            balance, args.agent_fund_amount, checker)
                    return Actor(phone=phone, user_id=entry["user_id"],
                                 session_token=entry["session_token"],
                                 pin=entry.get("pin", args.user_pin))
                except httpx.HTTPStatusError:
                    pass  # Session expired — fall through to a full re-provision.

            user_id = await ensure_typed_user(client, args, tokens, tenant_id, phone,
                                              f"Agent{idx}", "agent", parent_user_id=super_id)
            actor = await provision_actor(client, args, tokens, checker, tenant_id, phone,
                                          user_id, agent_role, args.agent_fund_amount)
            agent_cache[phone] = {
                "user_id": actor.user_id, "session_token": actor.session_token, "pin": actor.pin
            }
            provisioned += 1
            return actor

    agents: list[Actor] = []
    tasks = [one(i + 1) for i in range(args.agents)]
    batch = 100
    for start in range(0, len(tasks), batch):
        agents.extend(await asyncio.gather(*tasks[start:start + batch]))
        # Checkpoint every batch so a late failure doesn't discard the bcrypt work.
        save_json(args.mixed_state_file, cache)
        print(f"  agents: {min(start + batch, len(tasks)):>5}/{args.agents} "
              f"(newly provisioned: {provisioned}, cache checkpointed)", flush=True)
    return agents


async def setup_merchant(
    client: httpx.AsyncClient, args: argparse.Namespace, tokens: L.AdminTokenProvider,
    checker: L.AdminTokenProvider, tenant_id: str, cache: dict,
) -> tuple[Actor, list[tuple[str, str]]]:
    """Provision head_merchant -> merchant, fund it, and mint N API keys.

    Returns (merchant, [(key_id, secret), ...]). Keys are minted fresh each run:
    the plaintext secret is returned ONCE at creation and never retrievable
    again, so a cached key_id without its secret is useless for signing.
    """
    head_phone = "+27 87 100 00001"
    merch_phone = "+27 87 200 00001"
    head_id = await ensure_typed_user(client, args, tokens, tenant_id,
                                      head_phone, "HeadMerchant", "head_merchant")
    merch_id = await ensure_typed_user(client, args, tokens, tenant_id, merch_phone,
                                       "Merchant", "merchant", parent_user_id=head_id)
    merchant = await provision_actor(client, args, tokens, checker, tenant_id, merch_phone,
                                     merch_id, None, args.merchant_fund_amount)
    print(f"  + merchant funded ({merch_id[:8]}…)")

    keys: list[tuple[str, str]] = []
    for i in range(args.merchant_keys):
        resp = await client.post(f"{args.api_url}/api/v1/api-keys",
            headers=await tokens.header(),
            json={"tenant_id": tenant_id, "label": f"load-test-mixed-{i}-{uuid.uuid4().hex[:6]}",
                  "merchant_user_id": merch_id}, timeout=30)
        if resp.status_code != 201:
            L._fail("api-keys create", resp)
        body = resp.json()
        keys.append((body["key_id"], body["secret"]))
    print(f"  + {len(keys)} merchant API keys minted "
          f"(~{len(keys) * 60}/min ceiling before 429s)")
    cache["merchant"] = {"user_id": merch_id, "phone": merch_phone}
    save_json(args.mixed_state_file, cache)
    return merchant, keys


# ---------------------------------------------------------------------------
# The five operations
# ---------------------------------------------------------------------------

def _classify(resp: httpx.Response) -> str:
    """Best-effort `error_code` for a failed response, falling back to the status.

    A non-JSON body (proxy error page, empty 502) raises ValueError from .json(),
    and a JSON body that is not an object has no .get — both mean "no error_code
    to read", so the status line is the most specific label available.
    """
    try:
        return resp.json().get("error_code", f"http_{resp.status_code}")
    except (ValueError, AttributeError):
        return f"http_{resp.status_code}"


async def do_p2p(client, args, ctx, stats) -> None:
    sender, recipient = random.sample(ctx["consumers"], 2)
    await _fire(client, stats, "p2p",
        f"{args.api_url}/api/v1/payments/p2p",
        headers={"Authorization": f"Bearer {sender.session_token}",
                 "Idempotency-Key": uuid.uuid4().hex},
        json={"recipient": {"identifier_type": "phone", "identifier_value": recipient.phone},
              "amount": str(_amount(args)), "currency": "ZAR"})


async def do_cashout(client, args, ctx, stats) -> None:
    # A subscriber cashes out TO an agent — the recipient must be agent-typed.
    subscriber = random.choice(ctx["consumers"])
    agent = random.choice(ctx["agents"])
    await _fire(client, stats, "cashout",
        f"{args.api_url}/api/v1/cashout",
        headers={"Authorization": f"Bearer {subscriber.session_token}",
                 "Idempotency-Key": uuid.uuid4().hex},
        json={"identifier_type": "phone", "identifier_value": agent.phone,
              "amount": str(_amount(args)), "currency": "ZAR"})


async def do_airtime(client, args, ctx, stats) -> None:
    buyer = random.choice(ctx["consumers"])
    await _fire(client, stats, "airtime",
        f"{args.api_url}/api/v1/airtime/recharge",
        headers={"Authorization": f"Bearer {buyer.session_token}",
                 "Idempotency-Key": uuid.uuid4().hex},
        json={"msisdn": _sim_msisdn(), "network": random.choice(("MTN", "VODACOM", "CELLC")),
              "amount": str(_amount(args)), "currency": "ZAR"})


async def do_cash_in(client, args, ctx, stats) -> None:
    agent = random.choice(ctx["agents"])
    customer = random.choice(ctx["consumers"])
    await _fire(client, stats, "cash_in",
        f"{args.api_url}/api/v1/cashin",
        headers={"Authorization": f"Bearer {agent.session_token}",
                 "Idempotency-Key": uuid.uuid4().hex},
        json={"customer": {"identifier_type": "phone", "identifier_value": customer.phone},
              "amount": str(_amount(args)), "currency": "ZAR"})


async def do_merchant_cashin(client, args, ctx, stats) -> None:
    """External partner API: API key + HMAC over the exact body bytes."""
    customer = random.choice(ctx["consumers"])
    key_id, secret = next(ctx["key_cycle"])
    # Signature covers the bytes on the wire, so serialise once and send `content`.
    body = json.dumps({"identifier_type": "phone", "identifier_value": customer.phone,
                       "amount": str(_amount(args)), "currency": "ZAR",
                       "reason": "load test"}).encode()
    await _fire(client, stats, "merchant_cashin",
        f"{args.api_url}/api/v1/external/merchant-cashin",
        headers={"X-Sasai-Api-Key": key_id, "X-Sasai-Signature": sign_body(body, secret),
                 "Idempotency-Key": uuid.uuid4().hex, "Content-Type": "application/json"},
        content=body)


def _amount(args: argparse.Namespace) -> int:
    return random.randint(args.min_amount, args.max_amount)


def _sim_msisdn() -> str:
    """A simulator-safe msisdn.

    The SimulatorProvider forces `failed` on suffix 0001 and `pending` on 0002,
    so those are excluded — otherwise the run reports provider outcomes that are
    scripted test fixtures, not load failures.
    """
    while True:
        n = random.randint(3, 99_999)
        if n not in (1, 2):
            return f"+27 82 555 {n:05d}"


async def _fire(client: httpx.AsyncClient, stats: MixedStats, service: str,
                url: str, **kwargs) -> None:
    """Issue one request, timing it and classifying the outcome."""
    t0 = time.monotonic()
    try:
        resp = await client.post(url, timeout=30, **kwargs)
    except (httpx.HTTPError, TimeoutError) as exc:
        stats.record(service, False, (time.monotonic() - t0) * 1000, type(exc).__name__)
        return
    elapsed = (time.monotonic() - t0) * 1000
    ok = 200 <= resp.status_code < 300
    code = None if ok else _classify(resp)
    stats.record(service, ok, elapsed, code)
    if not ok and stats.per_service[service].error_codes[code] <= 2:
        print(f"  ! {service}/{code}: {resp.text[:170]}", flush=True)


OPS = {"p2p": do_p2p, "cashout": do_cashout, "airtime": do_airtime,
       "cash_in": do_cash_in, "merchant_cashin": do_merchant_cashin}


# ---------------------------------------------------------------------------
# Load phase + reporting
# ---------------------------------------------------------------------------

async def reporter(stats: MixedStats, duration: int) -> None:
    last = 0
    while True:
        await asyncio.sleep(5)
        elapsed = time.monotonic() - stats.started_at
        if elapsed >= duration:
            return
        done = stats.success + stats.failure
        tps_5s = (done - last) / 5
        last = done
        cutoff = time.monotonic() - 30
        tps_30s = sum(1 for ts in stats.completed if ts >= cutoff) / min(30, elapsed)
        mix = "  ".join(
            f"{s[:4]}={stats.per_service[s].success + stats.per_service[s].failure}"
            for s in SERVICES if stats.per_service[s].latencies_ms
        )
        print(f"  t={elapsed:>5.1f}s total={done:>6} 5s={tps_5s:>6.1f}/s "
              f"30s={tps_30s:>6.1f}/s ok={stats.success} fail={stats.failure}  [{mix}]",
              flush=True)


async def load_phase(client: httpx.AsyncClient, args: argparse.Namespace,
                     ctx: dict, weights: dict[str, int]) -> MixedStats:
    stats = MixedStats()
    stats.started_at = time.monotonic()
    names = list(weights)
    weight_values = [weights[n] for n in names]
    deadline = stats.started_at + args.duration
    rep = asyncio.create_task(reporter(stats, args.duration))

    async def worker() -> None:
        while time.monotonic() < deadline:
            service = random.choices(names, weights=weight_values, k=1)[0]
            await OPS[service](client, args, ctx, stats)

    await asyncio.gather(*(worker() for _ in range(args.concurrency)))
    rep.cancel()
    return stats


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * q), len(ordered) - 1)]


def print_summary(args: argparse.Namespace, stats: MixedStats,
                  weights: dict[str, int], wall: float, ctx: dict) -> None:
    total = stats.success + stats.failure
    print("\n" + "=" * 78)
    print("  CONSOLIDATED MULTI-SERVICE LOAD TEST — SUMMARY")
    print("=" * 78)
    print(f"  Consumers / agents   : {len(ctx['consumers'])} / {len(ctx['agents'])}")
    print(f"  Merchant API keys    : {len(ctx['keys'])}")
    print(f"  Concurrency          : {args.concurrency}")
    print(f"  Duration / wall      : {args.duration}s / {wall:.2f}s")
    print(f"  Amount range         : R{args.min_amount}-R{args.max_amount} (step-up at R200)")
    print(f"  Requests total       : {total}")
    print(f"  Successful / failed  : {stats.success} / {stats.failure}")
    print(f"  Aggregate TPS (all)  : {total / wall:.1f}")
    print(f"  Aggregate TPS (ok)   : {stats.success / wall:.1f}")
    print("-" * 78)
    print(f"  {'service':<17}{'req':>7}{'ok':>7}{'fail':>6}{'TPS':>8}"
          f"{'p50':>9}{'p95':>9}{'p99':>9}")
    print("-" * 78)
    for name in SERVICES:
        st = stats.per_service[name]
        n = st.success + st.failure
        if not n:
            continue
        print(f"  {name:<17}{n:>7}{st.success:>7}{st.failure:>6}"
              f"{n / wall:>8.1f}{pct(st.latencies_ms, 0.50):>8.0f}ms"
              f"{pct(st.latencies_ms, 0.95):>8.0f}ms{pct(st.latencies_ms, 0.99):>8.0f}ms")
    print("-" * 78)
    print(f"  Requested mix        : "
          f"{', '.join(f'{k}={v}' for k, v in weights.items())}")
    total_weight = sum(weights.values())
    print("  Achieved mix         : " + ", ".join(
        f"{s}={(stats.per_service[s].success + stats.per_service[s].failure) / total * 100:.0f}%"
        f"(want {weights.get(s, 0) / total_weight * 100:.0f}%)"
        for s in SERVICES if stats.per_service[s].latencies_ms))
    any_errors = False
    for name in SERVICES:
        st = stats.per_service[name]
        if st.error_codes:
            if not any_errors:
                print("  Errors by service    :")
                any_errors = True
            codes = ", ".join(f"{c} x{n}" for c, n in st.error_codes.most_common(5))
            print(f"    {name:<17} {codes}")
    if not any_errors:
        print("  Errors               : none")
    for name in SERVICES:
        lat = stats.per_service[name].latencies_ms
        if lat:
            print(f"  {name} mean latency: {statistics.mean(lat):.0f} ms", end="")
            print()
            break
    print("=" * 78)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    args = parse_args()
    weights = parse_weights(args.weights)
    print(f"Consolidated load test against {args.api_url}")
    print(f"Mix: {', '.join(f'{k}={v}' for k, v in weights.items())} — "
          f"{args.duration}s at concurrency {args.concurrency}")

    consumer_cache = load_json(args.state_file)
    mixed_cache = load_json(args.mixed_state_file)

    limits = httpx.Limits(max_connections=args.concurrency + 20,
                          max_keepalive_connections=args.concurrency + 20)
    async with httpx.AsyncClient(timeout=30, limits=limits) as client:
        print("== AUTH ==")
        tokens = L.AdminTokenProvider(client, args)
        await tokens.get()
        checker_args = argparse.Namespace(**{**vars(args),
                                             "admin_user": args.checker_user,
                                             "admin_pass": args.checker_pass})
        checker = L.AdminTokenProvider(client, checker_args)
        await checker.get()
        print(f"  + maker={args.admin_user} checker={args.checker_user}")

        print("== TENANT ==")
        tenant_id = await L.find_tenant_id(client, args.api_url, args.tenant_name, tokens)
        print(f"  + tenant '{args.tenant_name}' = {tenant_id}")

        print("== LIMITS PREFLIGHT ==")
        await L.ensure_permissive_p2p_limit(client, args.api_url, tokens, tenant_id)

        print("== ROLES ==")
        consumer_role = await ensure_role(
            client, args, tokens, tenant_id, "load-test-user",
            "Role used by the load-test scripts — grants p2p/cashout/airtime.",
            ("p2p", "cashout", "airtime_recharge"))
        print(f"  + consumer role ready ({consumer_role[:8]}…) "
              f"granting p2p, cashout, airtime_recharge")

        if args.no_fund:
            print("  ! --no-fund: transacting off existing balances only; a short "
                  "wallet will surface as a real `insufficient_funds` result.")

        # Provision only what the requested mix actually uses. Agents and the
        # merchant each cost real setup (two bcrypt rounds per actor, API-key
        # minting), so a p2p-only or cash_in-only run should not pay for pools it
        # never touches — and should not mutate state it never exercises.
        needs_agents = bool({"cash_in", "cashout"} & weights.keys())
        needs_merchant = "merchant_cashin" in weights

        print(f"== CONSUMERS ({args.users}) ==")
        consumers = await setup_consumers(client, args, tokens, checker,
                                          tenant_id, consumer_role, consumer_cache)
        if needs_agents:
            print(f"== AGENTS ({args.agents}) ==")
            agents = await setup_agents(client, args, tokens, checker, tenant_id, mixed_cache)
        else:
            agents = []
            print("== AGENTS == skipped (mix has no cash_in/cashout)")
        if needs_merchant:
            print("== MERCHANT + API KEYS ==")
            merchant, keys = await setup_merchant(client, args, tokens, checker,
                                                  tenant_id, mixed_cache)
        else:
            merchant, keys = None, []
            print("== MERCHANT == skipped (mix has no merchant_cashin)")

        if args.phase == "setup":
            print("setup-only mode: stopping before the load phase.")
            return

        from itertools import cycle
        ctx = {"consumers": consumers, "agents": agents, "merchant": merchant,
               "keys": keys, "key_cycle": cycle(keys)}

        print(f"== MIXED LOAD ({args.concurrency} concurrent, {args.duration}s) ==")
        t0 = time.monotonic()
        stats = await load_phase(client, args, ctx, weights)
        wall = time.monotonic() - t0
        print_summary(args, stats, weights, wall, ctx)


if __name__ == "__main__":
    asyncio.run(main())
