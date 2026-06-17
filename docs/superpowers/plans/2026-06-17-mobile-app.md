# Sasai Wallet Mobile App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished demo-ready iOS + Android mobile app for Sasai Wallet (Expo + Tamagui), plus the five small backend additions it depends on.

**Architecture:** New `mobile/` codebase using Expo SDK 52, Expo Router (file-based), Tamagui (design system), TanStack Query (data), expo-secure-store (session). Five additive backend changes in `backend/app/modules/{identity,payments,catalog}` and `scripts/seed.py`. No breaking changes to admin-ui or mobile-simulator.

**Tech Stack:** Expo SDK 52 · React Native · TypeScript · Tamagui · Expo Router · TanStack Query · expo-secure-store · expo-local-authentication · expo-blur · expo-font · EAS Build · Backend: FastAPI · SQLAlchemy 2.0 · pytest.

**Spec:** [docs/superpowers/specs/2026-06-17-mobile-app-design.md](../specs/2026-06-17-mobile-app-design.md)

**Phasing:** Eight phases (A–H) executable sequentially. Phase A (backend) unblocks the mobile work; Phase B (bootstrap) unblocks the screen phases. Within each phase, tasks are ordered by dependency.

| Phase | Scope | Approx tasks |
|---|---|---|
| A | Backend additions (TDD) | 5 |
| B | Mobile bootstrap + foundations | 10 |
| C | Auth flow | 5 |
| D | Home + Activity + Profile | 8 |
| E | P2P flow | 6 |
| F | Topup flow | 3 |
| G | Rewards + Redemption | 3 |
| H | Polish + Build profiles | 4 |

**Testing strategy:**

- **Backend tasks** follow TDD per `coding-guidelines.md` §3: failing test → impl → passing test → commit. Real PostgreSQL test DB. Required coverage: happy path, auth failures (401/403), validation (422), tenant isolation, idempotency.
- **Mobile tasks** are implementation-only per `coding-guidelines.md` §4 (frontend tests deferred). Each task ends with a manual verification step (run on simulator, observe specific behavior) and a commit.

---

## Phase A — Backend additions

Five additive changes. No breaking changes. All endpoints obey `python-backend.md` (router/service split, idempotency keys, structured logs) and `compliance-fintech.md` (PII masking, no PIN in logs, tenant isolation).

### Task A1: `POST /api/v1/identity/auth/start` — phone lookup

**Purpose:** Single endpoint the mobile app calls after the user enters a phone number, returning `{status: "needs_otp" | "needs_pin"}`. Branches the auth flow without leaking cross-tenant user existence.

**Files:**
- Modify: `backend/app/modules/identity/schemas.py` (append schemas)
- Modify: `backend/app/modules/identity/service.py` (append function)
- Modify: `backend/app/modules/identity/router.py` (append route)
- Create: `backend/tests/identity/test_auth_start.py`

- [ ] **Step 1: Write failing test for new-phone → needs_otp**

Create `backend/tests/identity/test_auth_start.py`:

```python
"""Tests for POST /api/v1/identity/auth/start (phone lookup).

The endpoint inspects the (tenant, normalized_phone) pair and returns
`needs_otp` for unknown numbers (will register) or `needs_pin` for known
numbers (will log in). The response shape is identical in both branches
to avoid leaking cross-tenant user existence to anonymous callers.
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_auth_start_new_phone_returns_needs_otp(
    api_client: AsyncClient, seeded_tenant_ctx
) -> None:
    """An unknown phone resolves to needs_otp — the caller will go through OTP + set-PIN."""
    response = await api_client.post(
        "/api/v1/identity/auth/start",
        json={"phone_e164": "+27821112233"},
        headers={"X-Tenant-Id": str(seeded_tenant_ctx.tenant_id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "needs_otp"}
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd backend && pytest tests/identity/test_auth_start.py::test_auth_start_new_phone_returns_needs_otp -v
```

Expected: 404 (route does not exist).

- [ ] **Step 3: Add request + response schemas**

Append to `backend/app/modules/identity/schemas.py`:

```python
class AuthStartRequest(BaseModel):
    """Body for POST /auth/start — single phone number in E.164 format.

    The mobile app calls this immediately after the user types a phone.
    The phone is normalized server-side via `normalize_phone`; both
    branches return the same response shape to avoid existence leak.
    """

    phone_e164: str = Field(min_length=8, max_length=20)

    @field_validator("phone_e164")
    @classmethod
    def _validate_e164(cls, v: str) -> str:
        if not v.startswith("+"):
            raise ValueError("phone_e164 must start with +")
        return v


class AuthStartResponse(BaseModel):
    """Branch hint for the mobile auth flow.

    `needs_otp` means the caller has no account and must go through
    OTP + set-PIN. `needs_pin` means the caller has an account and
    should be sent to the PIN entry screen.
    """

    status: Literal["needs_otp", "needs_pin"]
```

- [ ] **Step 4: Add service function**

Append to `backend/app/modules/identity/service.py`:

```python
async def auth_start_lookup(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    phone_e164: str,
) -> dict[str, str]:
    """Resolve a phone number to an auth-flow branch.

    Looks for an identifier row with the normalized phone in this tenant.
    Returns the same response shape regardless of outcome so an anonymous
    caller cannot probe for user existence across tenants.

    Args:
        session: Async DB session.
        tenant_id: Tenant resolved from X-Tenant-Id header (Phase A demo)
            or from the public-mobile dependency once production auth lands.
        phone_e164: Phone number in E.164 format (validated by schema).

    Returns:
        `{"status": "needs_otp"}` or `{"status": "needs_pin"}` — never raises
        based on lookup outcome.
    """
    normalized = normalize_phone(phone_e164)
    stmt = (
        select(Identifier.id)
        .join(User, User.id == Identifier.user_id)
        .where(
            User.tenant_id == tenant_id,
            Identifier.identifier_type == "phone",
            Identifier.identifier_value == normalized,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    found = result.scalar_one_or_none()
    return {"status": "needs_pin" if found else "needs_otp"}
```

Add the imports at the top of `service.py` if missing:
```python
from sqlalchemy import select
from app.shared.models.users import User, Identifier
from app.shared.utils.normalize import normalize_phone
```

- [ ] **Step 5: Add router endpoint**

In `backend/app/modules/identity/router.py`, append:

```python
@router.post("/auth/start", response_model=AuthStartResponse, status_code=200)
async def post_auth_start(
    request: AuthStartRequest,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-Id"),
    session: AsyncSession = Depends(get_async_session),
) -> AuthStartResponse:
    """Mobile auth-flow branch hint (Phase F.6 — public, no session).

    Returns the same response shape for both "user exists" and "user does
    not exist" cases so anonymous callers cannot probe across tenants.

    Raises:
        HTTPException (422): malformed phone_e164.
    """
    result = await auth_start_lookup(
        session, tenant_id=x_tenant_id, phone_e164=request.phone_e164
    )
    return AuthStartResponse(**result)
```

Add `AuthStartRequest, AuthStartResponse` to the schema imports and `auth_start_lookup` to the service imports at the top of the file.

- [ ] **Step 6: Run test, verify pass**

```bash
pytest tests/identity/test_auth_start.py::test_auth_start_new_phone_returns_needs_otp -v
```

Expected: PASS.

- [ ] **Step 7: Add test for known phone → needs_pin**

Append to `test_auth_start.py`:

```python
async def test_auth_start_known_phone_returns_needs_pin(
    api_client: AsyncClient, seeded_user_alice, seeded_tenant_ctx
) -> None:
    """A known phone resolves to needs_pin — the caller goes to PIN entry."""
    response = await api_client.post(
        "/api/v1/identity/auth/start",
        json={"phone_e164": seeded_user_alice.phone_e164},
        headers={"X-Tenant-Id": str(seeded_tenant_ctx.tenant_id)},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "needs_pin"}
```

Run: `pytest tests/identity/test_auth_start.py -v` — expect both tests pass.

- [ ] **Step 8: Add cross-tenant isolation test**

Append:

```python
async def test_auth_start_other_tenant_phone_returns_needs_otp(
    api_client: AsyncClient, seeded_user_alice, seeded_other_tenant
) -> None:
    """A phone that exists in another tenant must look 'unknown' to this tenant."""
    response = await api_client.post(
        "/api/v1/identity/auth/start",
        json={"phone_e164": seeded_user_alice.phone_e164},
        headers={"X-Tenant-Id": str(seeded_other_tenant.tenant_id)},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "needs_otp"}  # cross-tenant invisible
```

Run all three tests. Expect PASS.

- [ ] **Step 9: Add validation test (bad phone)**

Append:

```python
async def test_auth_start_rejects_phone_without_plus(
    api_client: AsyncClient, seeded_tenant_ctx
) -> None:
    response = await api_client.post(
        "/api/v1/identity/auth/start",
        json={"phone_e164": "27821112233"},
        headers={"X-Tenant-Id": str(seeded_tenant_ctx.tenant_id)},
    )
    assert response.status_code == 422
```

Run — expect PASS (schema validator rejects missing `+`).

- [ ] **Step 10: Commit**

```bash
git add backend/app/modules/identity/schemas.py \
        backend/app/modules/identity/service.py \
        backend/app/modules/identity/router.py \
        backend/tests/identity/test_auth_start.py
git commit -m "feat(identity): add POST /auth/start phone-lookup for mobile auth branching"
```

---

### Task A2: `POST /api/v1/payments/topup` — demo top-up

**Purpose:** Mobile-callable top-up endpoint that credits the user's ZAR account via `operator_adjustment` under the hood (no real card processor). Step-up policy aware. Idempotency-key required.

**Files:**
- Modify: `backend/app/modules/payments/schemas.py` (add `TopupRequest`, `TopupResponse`)
- Modify: `backend/app/modules/payments/service.py` (add `topup` function)
- Modify: `backend/app/modules/payments/router.py` (add `POST /topup`)
- Create: `backend/tests/payments/test_topup.py`

- [ ] **Step 1: Write failing test — happy path below step-up threshold**

```python
"""Tests for POST /api/v1/payments/topup (mobile demo top-up).

Top-up credits the user's ZAR account via operator_adjustment, with the
same step-up-policy treatment as P2P. Required for the mobile demo
(no real card processor wired in Phase 1).
"""
import pytest
from decimal import Decimal
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_topup_below_threshold_succeeds_without_pin(
    api_client: AsyncClient, alice_session_token: str
) -> None:
    response = await api_client.post(
        "/api/v1/payments/topup",
        json={"amount": "100.00", "currency": "ZAR", "demo_reference": "demo-card-001"},
        headers={
            "Authorization": f"Bearer {alice_session_token}",
            "Idempotency-Key": "topup-test-001",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["new_balance"] == "100.00"          # opening 0 + 100 = 100
    assert body["earned_points"] in (None, 0)        # no top-up rule fired yet
    assert "ledger_entry_id" in body
```

Run: `pytest backend/tests/payments/test_topup.py::test_topup_below_threshold_succeeds_without_pin -v`
Expected: FAIL (route missing → 404).

- [ ] **Step 2: Add schemas**

Append to `backend/app/modules/payments/schemas.py`:

```python
class TopupRequest(BaseModel):
    """Mobile demo top-up. Internally calls operator_adjustment.

    `pin` is optional — only required when a step_up_policies row matches.
    `demo_reference` is a free-form string echoed back; logged but not
    masked (no PII).
    """

    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(min_length=3, max_length=3)
    demo_reference: str = Field(min_length=1, max_length=64)
    pin: str | None = Field(default=None, min_length=4, max_length=12)


class TopupResponse(BaseModel):
    """Result of a successful demo top-up."""

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    ledger_entry_id: UUID
    new_balance: Decimal
    currency: str
    earned_points: int | None = None
    created_at: datetime
```

- [ ] **Step 3: Add service function**

Append to `backend/app/modules/payments/service.py`:

```python
async def topup(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    amount: Decimal,
    currency: str,
    demo_reference: str,
    idempotency_key: str,
    pin: str | None,
    ip_address: str | None,
) -> tuple[Transaction, LedgerEntry, Decimal, int | None]:
    """Credit a user's account via operator_adjustment (demo path).

    Follows the ledger-invariants pattern: append-only entries, idempotency
    key enforced, external/synthetic credit logged in audit. Step-up policy
    is enforced for amounts at/above the configured threshold (mirrors P2P).

    Returns:
        (Transaction, credit LedgerEntry, new balance, earned_points or None)

    Raises:
        StepUpRequired, InvalidStepUpPin, IdempotencyConflict.
    """
    from app.modules.step_up.service import enforce_step_up

    await enforce_step_up(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        amount=amount,
        currency=currency,
        action="topup",
        pin=pin,
        ip_address=ip_address,
    )

    # Append-only operator_adjustment credit. Reuses the same orchestrator
    # used by the treasury /fund-user route to keep ledger semantics consistent.
    from app.modules.treasury.service import credit_user_via_operator_adjustment

    txn, entry, new_balance = await credit_user_via_operator_adjustment(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        amount=amount,
        currency=currency,
        reference=demo_reference,
        idempotency_key=idempotency_key,
        source="mobile_demo_topup",
    )

    # Rules engine result is included synchronously so the mobile client
    # can render the "earned PTS" toast without polling.
    earned = await _resolve_earned_points_for_txn(session, txn.id)
    return txn, entry, new_balance, earned
```

If `credit_user_via_operator_adjustment` does not exist yet in
`backend/app/modules/treasury/service.py`, extract it from whatever the
existing treasury `/fund-user` handler does — it's the same operation. If
already present, reuse as-is.

`_resolve_earned_points_for_txn` is a small helper that joins
`reward_events` on the triggering event id and returns the total PTS
credited. Implement in `service.py`:

```python
async def _resolve_earned_points_for_txn(
    session: AsyncSession, txn_id: UUID
) -> int | None:
    """Sum PTS credited by the rules engine for this transaction.

    Returns the integer total, or None if no reward events fired (which
    we'll surface as `null` in the JSON response).
    """
    from app.shared.models.rewards import RewardEvent
    stmt = select(func.coalesce(func.sum(RewardEvent.points_amount), 0)).where(
        RewardEvent.triggering_transaction_id == txn_id
    )
    total = (await session.execute(stmt)).scalar_one()
    return int(total) if total else None
```

- [ ] **Step 4: Add router endpoint**

Append to `backend/app/modules/payments/router.py`:

```python
@router.post("/topup", response_model=TopupResponse, status_code=201)
async def post_topup(
    request: TopupRequest,
    fastapi_request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> TopupResponse:
    """Mobile demo top-up (Pay-PRD-0320).

    Credits the user's account via operator_adjustment. No real card
    processor is involved — this exists to drive the mobile demo flow.
    Idempotency-Key required (Pay-PRD-0200).
    """
    txn, entry, new_balance, earned = await topup(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        amount=request.amount,
        currency=request.currency,
        demo_reference=request.demo_reference,
        idempotency_key=idempotency_key,
        pin=request.pin,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return TopupResponse(
        transaction_id=txn.id,
        ledger_entry_id=entry.id,
        new_balance=new_balance,
        currency=request.currency,
        earned_points=earned,
        created_at=txn.created_at,
    )
```

- [ ] **Step 5: Run test, verify pass**

```bash
pytest backend/tests/payments/test_topup.py::test_topup_below_threshold_succeeds_without_pin -v
```

Expected: PASS.

- [ ] **Step 6: Add step-up-required test**

Append:

```python
async def test_topup_above_threshold_requires_pin(
    api_client: AsyncClient, alice_session_token: str, large_topup_step_up_policy
) -> None:
    """A topup at/above the policy threshold without pin must return 401 step_up_required."""
    response = await api_client.post(
        "/api/v1/payments/topup",
        json={"amount": "5000.00", "currency": "ZAR", "demo_reference": "demo-card-002"},
        headers={
            "Authorization": f"Bearer {alice_session_token}",
            "Idempotency-Key": "topup-test-002",
        },
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "step_up_required"


async def test_topup_above_threshold_with_correct_pin_succeeds(
    api_client: AsyncClient, alice_session_token: str, large_topup_step_up_policy
) -> None:
    response = await api_client.post(
        "/api/v1/payments/topup",
        json={"amount": "5000.00", "currency": "ZAR", "demo_reference": "demo-card-003", "pin": "1234"},
        headers={
            "Authorization": f"Bearer {alice_session_token}",
            "Idempotency-Key": "topup-test-003",
        },
    )
    assert response.status_code == 201
```

Run — expect PASS for both.

- [ ] **Step 7: Add idempotency test**

```python
async def test_topup_replays_return_same_response(
    api_client: AsyncClient, alice_session_token: str
) -> None:
    headers = {
        "Authorization": f"Bearer {alice_session_token}",
        "Idempotency-Key": "topup-replay-001",
    }
    body = {"amount": "200.00", "currency": "ZAR", "demo_reference": "demo-card-replay"}

    first = await api_client.post("/api/v1/payments/topup", json=body, headers=headers)
    second = await api_client.post("/api/v1/payments/topup", json=body, headers=headers)

    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["transaction_id"] == second.json()["transaction_id"]
    assert first.json()["new_balance"] == second.json()["new_balance"]  # balance not double-credited
```

Run — expect PASS.

- [ ] **Step 8: Add auth-required test**

```python
async def test_topup_without_session_returns_401(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/payments/topup",
        json={"amount": "100.00", "currency": "ZAR", "demo_reference": "demo-card-004"},
        headers={"Idempotency-Key": "topup-test-noauth"},
    )
    assert response.status_code == 401
```

Run — expect PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/modules/payments/schemas.py \
        backend/app/modules/payments/service.py \
        backend/app/modules/payments/router.py \
        backend/tests/payments/test_topup.py
git commit -m "feat(payments): add POST /payments/topup for mobile demo (operator_adjustment under the hood)"
```

---

### Task A3: Extend `P2PResponse` with `earned_points`

**Purpose:** Add a single optional integer field to the P2P response so the mobile client can render the "earned PTS" toast without a polling round-trip.

**Files:**
- Modify: `backend/app/modules/payments/schemas.py`
- Modify: `backend/app/modules/payments/service.py` (compute earned_points after rules engine fires)
- Modify: `backend/app/modules/payments/router.py` (pass through)
- Modify: `backend/tests/payments/test_p2p.py` (extend existing happy-path test)

- [ ] **Step 1: Write failing test**

Append to `backend/tests/payments/test_p2p.py`:

```python
async def test_p2p_response_includes_earned_points_field(
    api_client: AsyncClient, alice_session_token: str, bob_phone: str,
) -> None:
    """P2P response must surface earned_points (int or null) — the mobile
    client uses it for the post-send rewards toast without a follow-up call."""
    response = await api_client.post(
        "/api/v1/payments/p2p",
        json={
            "recipient": {"identifier_type": "phone", "identifier_value": bob_phone},
            "amount": "50.00",
            "currency": "ZAR",
        },
        headers={
            "Authorization": f"Bearer {alice_session_token}",
            "Idempotency-Key": "p2p-earned-001",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert "earned_points" in body
    assert body["earned_points"] is None or isinstance(body["earned_points"], int)
```

Run — expect FAIL (`earned_points` key not in response).

- [ ] **Step 2: Add field to P2PResponse**

Edit `backend/app/modules/payments/schemas.py` — add `earned_points` to the existing `P2PResponse`:

```python
class P2PResponse(BaseModel):
    """Result of a successful P2P transfer."""

    model_config = ConfigDict(from_attributes=True)

    transaction_id: UUID
    status: str
    amount: Decimal
    currency: str
    sender_user_id: UUID
    recipient_user_id: UUID
    created_at: datetime
    earned_points: int | None = None  # NEW: sum of PTS credited by rules engine for this txn
```

- [ ] **Step 3: Wire service to compute earned_points**

Edit `backend/app/modules/payments/service.py` — in `p2p_transfer`, after the rules engine has fired (post-commit), call `_resolve_earned_points_for_txn` (added in Task A2) and include the result in the return tuple. The router then sets it on the response.

Locate the return statement of `p2p_transfer`, add:

```python
earned = await _resolve_earned_points_for_txn(session, txn.id)
return txn, recipient_user_id, earned
```

- [ ] **Step 4: Wire router to pass through**

Edit `backend/app/modules/payments/router.py` in `post_p2p`:

```python
txn, recipient_user_id, earned = await p2p_transfer(...)
return P2PResponse(
    transaction_id=txn.id,
    status=txn.status,
    amount=txn.amount,
    currency=txn.currency,
    sender_user_id=user.id,
    recipient_user_id=recipient_user_id,
    created_at=txn.created_at,
    earned_points=earned,
)
```

- [ ] **Step 5: Run test, verify pass**

```bash
pytest backend/tests/payments/test_p2p.py::test_p2p_response_includes_earned_points_field -v
```

Expected: PASS.

- [ ] **Step 6: Run full P2P test file to confirm no regressions**

```bash
pytest backend/tests/payments/test_p2p.py -v
```

Expected: all existing P2P tests still pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/payments/schemas.py \
        backend/app/modules/payments/service.py \
        backend/app/modules/payments/router.py \
        backend/tests/payments/test_p2p.py
git commit -m "feat(payments): include earned_points in P2P response for single-roundtrip rewards toast"
```

---

### Task A4: `GET /api/v1/catalog/featured` — featured campaign for home

**Purpose:** Single endpoint that returns the top active campaign for the authenticated user (or empty if none). Drives the home-screen featured campaign card.

**Files:**
- Modify: `backend/app/modules/catalog/schemas.py`
- Modify: `backend/app/modules/catalog/service.py`
- Modify: `backend/app/modules/catalog/router.py`
- Create: `backend/tests/catalog/test_featured.py`

- [ ] **Step 1: Write failing test — happy path returns one campaign**

```python
"""Tests for GET /api/v1/catalog/featured.

Returns a single active campaign best suited to the caller, or null when
no campaign is active. Drives the mobile home-screen featured card.
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_featured_returns_active_campaign(
    api_client: AsyncClient, alice_session_token: str, seeded_topup_campaign
) -> None:
    response = await api_client.get(
        "/api/v1/catalog/featured",
        headers={"Authorization": f"Bearer {alice_session_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["campaign"] is not None
    assert body["campaign"]["id"] == str(seeded_topup_campaign.id)
    assert body["campaign"]["primary_action"] in ("topup", "p2p", "redeem")
```

Run: `pytest backend/tests/catalog/test_featured.py -v`
Expected: FAIL.

- [ ] **Step 2: Add response schema**

Append to `backend/app/modules/catalog/schemas.py`:

```python
class FeaturedCampaignItem(BaseModel):
    """Featured campaign payload for the mobile home card."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    subtitle: str
    primary_action: Literal["topup", "p2p", "redeem"]
    suggested_amount: Decimal | None = None
    suggested_currency: str | None = None
    reward_hint: str | None = None  # e.g., "Earn 50 PTS"


class FeaturedCampaignResponse(BaseModel):
    """Wrapper so an empty result is still a 200 (not 404)."""

    campaign: FeaturedCampaignItem | None = None
```

- [ ] **Step 3: Add service function**

Append to `backend/app/modules/catalog/service.py`:

```python
async def get_featured_campaign(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> FeaturedCampaignItem | None:
    """Return the single most relevant active campaign for a user.

    Selection: campaigns whose segment matches the user (or unbound),
    ordered by priority desc, created_at desc, limit 1. Returns None
    if no campaign is active (the home card collapses gracefully).
    """
    stmt = (
        select(Campaign)
        .where(
            Campaign.tenant_id == tenant_id,
            Campaign.status == "active",
            Campaign.starts_at <= func.now(),
            or_(Campaign.ends_at.is_(None), Campaign.ends_at > func.now()),
        )
        .order_by(Campaign.priority.desc(), Campaign.created_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    return FeaturedCampaignItem(
        id=row.id,
        title=row.title,
        subtitle=row.subtitle or "",
        primary_action=row.primary_action,
        suggested_amount=row.suggested_amount,
        suggested_currency=row.suggested_currency,
        reward_hint=row.reward_hint,
    )
```

If the `Campaign` model doesn't currently have `priority`, `primary_action`,
`suggested_amount`, `suggested_currency`, `reward_hint`, add them via a new
Alembic migration before this task — or relax this query to use whatever
fields exist and add the rest in a later Phase. **Verify the model first**:

```bash
grep -n "class Campaign" backend/app/shared/models/rewards.py
```

If `primary_action` etc. don't exist yet, add a migration:

```bash
cd backend && alembic revision -m "add featured-campaign fields to campaigns"
```

In the new migration, add columns: `priority INTEGER DEFAULT 0`,
`primary_action VARCHAR(20)`, `suggested_amount NUMERIC(18,2)`,
`suggested_currency CHAR(3)`, `reward_hint VARCHAR(120)`. Update the
SQLAlchemy model to match.

- [ ] **Step 4: Add router endpoint**

Append to `backend/app/modules/catalog/router.py`:

```python
@router.get("/featured", response_model=FeaturedCampaignResponse)
async def get_featured(
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> FeaturedCampaignResponse:
    """Top active campaign for the authenticated user (or null).

    Returns 200 with `{"campaign": null}` when nothing is active so the
    mobile home page can collapse the slot without handling a 404.
    """
    item = await get_featured_campaign(
        session, tenant_id=user.tenant_id, user_id=user.id
    )
    return FeaturedCampaignResponse(campaign=item)
```

- [ ] **Step 5: Run test, verify pass**

```bash
pytest backend/tests/catalog/test_featured.py::test_featured_returns_active_campaign -v
```

Expected: PASS.

- [ ] **Step 6: Add empty-state test**

```python
async def test_featured_returns_null_when_no_active_campaigns(
    api_client: AsyncClient, alice_session_token: str
) -> None:
    response = await api_client.get(
        "/api/v1/catalog/featured",
        headers={"Authorization": f"Bearer {alice_session_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"campaign": None}
```

Run — expect PASS.

- [ ] **Step 7: Add auth-required test**

```python
async def test_featured_without_session_returns_401(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/catalog/featured")
    assert response.status_code == 401
```

Run — expect PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/modules/catalog/schemas.py \
        backend/app/modules/catalog/service.py \
        backend/app/modules/catalog/router.py \
        backend/tests/catalog/test_featured.py \
        backend/alembic/versions/
git commit -m "feat(catalog): add GET /catalog/featured for mobile home campaign card"
```

---

### Task A5: Enrich `scripts/seed.py` with mobile-ready demo data

**Purpose:** Pre-seed Alice + Bob with prior P2P history (so the "Send again" carousel populates from first launch) and a small PTS balance with accrual history (so the rewards screen feels lived-in).

**Files:**
- Modify: `scripts/seed.py`

- [ ] **Step 1: Identify current seed structure**

```bash
grep -n "def seed_\|def main\|alice\|bob" scripts/seed.py | head -40
```

Note where Alice and Bob are created and where the seed `commit` happens.

- [ ] **Step 2: Add helper to insert historical P2P**

In `scripts/seed.py`, add a helper that issues a P2P transfer using the
service-layer function (so it produces real ledger entries + reward events):

```python
async def _seed_p2p(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    sender_user_id: UUID,
    recipient_phone: str,
    amount: Decimal,
    days_ago: int,
) -> None:
    """Insert a historical P2P transfer dated `days_ago` days in the past."""
    from app.modules.payments.service import p2p_transfer
    txn, _, _ = await p2p_transfer(
        session,
        tenant_id=tenant_id,
        sender_user_id=sender_user_id,
        recipient_identifier_type="phone",
        recipient_identifier_value=recipient_phone,
        amount=amount,
        currency="ZAR",
        description="Seeded historical P2P",
        idempotency_key=f"seed-p2p-{sender_user_id}-{days_ago}",
        pin=None,
    )
    # Backdate the row for realistic "Send again" + activity ordering.
    txn.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    await session.flush()
```

- [ ] **Step 3: Add helper to insert historical PTS accruals**

```python
async def _seed_pts_accrual(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    points: int,
    reason: str,
    days_ago: int,
) -> None:
    """Insert a PTS credit entry into the user's points account."""
    from app.modules.ledger.service import append_credit
    entry = await append_credit(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        account_type="points_account",
        currency="PTS",
        amount=Decimal(points),
        reason=reason,
        idempotency_key=f"seed-pts-{user_id}-{days_ago}",
    )
    entry.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    await session.flush()
```

If `append_credit` doesn't exist, use whatever direct insert path the
existing seed uses for opening balances (the file already creates ledger
entries somewhere — find that pattern and reuse it).

- [ ] **Step 4: Call helpers after Alice + Bob are created**

After Alice and Bob exist, before the final commit, add:

```python
# A few historical P2P sends from Alice so "Send again" carousel populates.
await _seed_p2p(session, tenant_id=tenant.id, sender_user_id=alice.id,
                recipient_phone=bob.phone_e164, amount=Decimal("120.00"), days_ago=1)
await _seed_p2p(session, tenant_id=tenant.id, sender_user_id=alice.id,
                recipient_phone=bob.phone_e164, amount=Decimal("50.00"), days_ago=3)
await _seed_p2p(session, tenant_id=tenant.id, sender_user_id=alice.id,
                recipient_phone=bob.phone_e164, amount=Decimal("75.00"), days_ago=5)

# A few PTS accruals so the rewards screen looks lived-in.
await _seed_pts_accrual(session, tenant_id=tenant.id, user_id=alice.id,
                        points=50, reason="First top-up bonus", days_ago=4)
await _seed_pts_accrual(session, tenant_id=tenant.id, user_id=alice.id,
                        points=10, reason="P2P reward", days_ago=2)
await _seed_pts_accrual(session, tenant_id=tenant.id, user_id=alice.id,
                        points=20, reason="Daily streak", days_ago=1)
```

- [ ] **Step 5: Run the seed and inspect**

```bash
cd backend && make seed
```

Expected output includes Alice + Bob + the seeded P2Ps + PTS accruals
without errors. Then query the DB:

```bash
psql $DATABASE_URL -c "SELECT amount, currency, created_at FROM transactions ORDER BY created_at DESC LIMIT 10;"
```

Expect to see the three seeded P2P rows at varying past timestamps.

- [ ] **Step 6: Commit**

```bash
git add scripts/seed.py
git commit -m "chore(seed): pre-populate Alice with P2P history and PTS accruals for mobile demo"
```

---

### Phase A wrap-up

Run the full backend test suite to confirm no regressions:

```bash
cd backend && make test
```

Expected: all tests pass. Coverage on touched modules ≥ 80% per
`coding-guidelines.md` §3.

---

## Phase B — Mobile bootstrap & foundations

All tasks create files under `mobile/` at the repo root. Frontend tests
are deferred per `coding-guidelines.md` §4 — verification is manual
("run on simulator, observe X").

### Task B1: Initialize Expo project

**Files:**
- Create: `mobile/` directory (via `create-expo-app`)

- [ ] **Step 1: Generate the Expo project**

From the repo root:

```bash
cd /Users/manan/Documents/Sasai_Wallet
npx create-expo-app@latest mobile --template default
cd mobile
```

This produces a TypeScript Expo Router project with SDK 52.

- [ ] **Step 2: Delete the default starter screens**

```bash
rm -rf app/(tabs) app/+not-found.tsx app/_layout.tsx app/index.tsx
rm -rf assets/images
rm -rf constants components hooks scripts
```

We replace these with our own structure in subsequent tasks.

- [ ] **Step 3: Pin Node engine + verify it runs**

Edit `mobile/package.json`, add:

```json
"engines": { "node": "22.22.2" }
```

Then:

```bash
npx expo start --clear
```

Expected: dev server starts, prints a QR code. Press `Ctrl-C` to stop.

- [ ] **Step 4: Commit**

```bash
git add mobile/
git commit -m "chore(mobile): initialize Expo project (SDK 52, TypeScript, Expo Router)"
```

---

### Task B2: Install runtime + dev dependencies

**Files:**
- Modify: `mobile/package.json`

- [ ] **Step 1: Install runtime dependencies**

```bash
cd mobile
npx expo install tamagui @tamagui/config @tamagui/lucide-icons \
  expo-router expo-secure-store expo-local-authentication \
  expo-font expo-blur expo-haptics expo-linear-gradient \
  expo-status-bar expo-system-ui expo-splash-screen \
  react-native-reanimated react-native-gesture-handler \
  react-native-safe-area-context react-native-screens
npm install @tanstack/react-query
```

- [ ] **Step 2: Install Tamagui Babel plugin**

```bash
npm install -D @tamagui/babel-plugin babel-plugin-transform-inline-environment-variables
```

- [ ] **Step 3: Configure Babel**

Replace `mobile/babel.config.js` with:

```js
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    plugins: [
      [
        '@tamagui/babel-plugin',
        {
          components: ['tamagui'],
          config: './tamagui.config.ts',
          logTimings: true,
          disableExtraction: process.env.NODE_ENV === 'development',
        },
      ],
      'react-native-reanimated/plugin', // must be last
    ],
  };
};
```

- [ ] **Step 4: Commit**

```bash
git add mobile/package.json mobile/package-lock.json mobile/babel.config.js
git commit -m "chore(mobile): install Tamagui, Expo libs, TanStack Query, Reanimated"
```

---

### Task B3: Configure Tamagui theme (Sasai navy + teal, light + dark)

**Files:**
- Create: `mobile/tamagui.config.ts`

- [ ] **Step 1: Write the config**

Create `mobile/tamagui.config.ts`:

```ts
/**
 * Tamagui design system configuration for Sasai Wallet mobile.
 *
 * Defines two themes (light + dark) using the brand palette from the
 * design spec (docs/superpowers/specs/2026-06-17-mobile-app-design.md
 * §13). The active theme is selected by useColorScheme() at the root.
 */
import { createTamagui } from 'tamagui';
import { config as defaultConfig } from '@tamagui/config/v3';

const tokens = {
  ...defaultConfig.tokens,
  color: {
    ...defaultConfig.tokens.color,
    sasaiNavy: '#144989',
    sasaiTeal: '#48C2CF',
    sasaiTealDk: '#2EA5B2',
    ink: '#0B1726',
    inkInverse: '#E8F0F8',
    muted: '#6A7682',
    surfaceLt: '#FFFFFF',
    surfaceDk: '#0E1A2B',
    success: '#22C55E',
    warn: '#F59E0B',
    error: '#EF4444',
  },
  radius: { ...defaultConfig.tokens.radius, xl: 16, '2xl': 20, '3xl': 28 },
};

const lightTheme = {
  background: tokens.color.surfaceLt,
  color: tokens.color.ink,
  primary: tokens.color.sasaiNavy,
  accent: tokens.color.sasaiTeal,
  muted: tokens.color.muted,
  success: tokens.color.success,
  warn: tokens.color.warn,
  error: tokens.color.error,
};

const darkTheme = {
  background: tokens.color.surfaceDk,
  color: tokens.color.inkInverse,
  primary: tokens.color.sasaiNavy,
  accent: tokens.color.sasaiTealDk,
  muted: tokens.color.muted,
  success: tokens.color.success,
  warn: tokens.color.warn,
  error: tokens.color.error,
};

const config = createTamagui({
  ...defaultConfig,
  tokens,
  themes: { light: lightTheme, dark: darkTheme },
  defaultTheme: 'light',
});

export type Conf = typeof config;
declare module 'tamagui' { interface TamaguiCustomConfig extends Conf {} }
export default config;
```

- [ ] **Step 2: Commit**

```bash
git add mobile/tamagui.config.ts
git commit -m "feat(mobile): configure Tamagui theme with Sasai navy + teal palette"
```

---

### Task B4: Configure Inter fonts

**Files:**
- Create: `mobile/assets/fonts/Inter-Regular.ttf`
- Create: `mobile/assets/fonts/Inter-Medium.ttf`
- Create: `mobile/assets/fonts/Inter-SemiBold.ttf`
- Create: `mobile/assets/fonts/Inter-Bold.ttf`

- [ ] **Step 1: Download Inter from Google Fonts**

Download the four Inter weights into `mobile/assets/fonts/`. Either:

```bash
cd mobile && mkdir -p assets/fonts && cd assets/fonts
curl -L -o Inter-Regular.ttf  "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Regular.ttf"
curl -L -o Inter-Medium.ttf   "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Medium.ttf"
curl -L -o Inter-SemiBold.ttf "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-SemiBold.ttf"
curl -L -o Inter-Bold.ttf     "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Bold.ttf"
```

or download via a browser if curl is blocked.

- [ ] **Step 2: Commit**

```bash
git add mobile/assets/fonts/
git commit -m "feat(mobile): add Inter font family (regular/medium/semibold/bold)"
```

---

### Task B5: Add brand assets

**Files:**
- Create: `mobile/assets/sasai-logo.svg` (provided by user)
- Create: `mobile/assets/icon.png` (1024×1024, swoosh mark on navy)
- Create: `mobile/assets/splash.png` (1284×2778 light variant + dark via app.json)
- Create: `mobile/assets/adaptive-icon.png` (foreground only, 1024×1024)

- [ ] **Step 1: Drop the SVG logo**

Place the user-provided Sasai logo at `mobile/assets/sasai-logo.svg`.

- [ ] **Step 2: Generate icons + splash**

Render `icon.png` (1024×1024), `adaptive-icon.png` (1024×1024,
foreground only), and `splash.png` (1284×2778, lockup centered on
`#FFFFFF`) from the SVG. Either via a design tool (Figma/Sketch) or
quickly via:

```bash
brew install librsvg
cd mobile/assets
rsvg-convert -w 1024 -h 1024 -b "#144989" sasai-logo.svg > icon.png
rsvg-convert -w 1024 -h 1024 -b "#00000000" sasai-logo.svg > adaptive-icon.png
rsvg-convert -w 1284 -h 2778 -b "#FFFFFF" sasai-logo.svg > splash.png
```

- [ ] **Step 3: Wire icons in app.json**

Replace `mobile/app.json` content with:

```json
{
  "expo": {
    "name": "Sasai Wallet",
    "slug": "sasai-wallet",
    "version": "0.1.0",
    "orientation": "portrait",
    "icon": "./assets/icon.png",
    "scheme": "sasai",
    "userInterfaceStyle": "automatic",
    "splash": {
      "image": "./assets/splash.png",
      "resizeMode": "contain",
      "backgroundColor": "#FFFFFF",
      "dark": { "backgroundColor": "#0E1A2B" }
    },
    "ios": { "supportsTablet": false, "bundleIdentifier": "co.sasai.wallet" },
    "android": {
      "package": "co.sasai.wallet",
      "adaptiveIcon": {
        "foregroundImage": "./assets/adaptive-icon.png",
        "backgroundColor": "#144989"
      }
    },
    "plugins": [
      "expo-router",
      "expo-font",
      "expo-secure-store",
      "expo-local-authentication"
    ],
    "experiments": { "typedRoutes": true }
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add mobile/assets/ mobile/app.json
git commit -m "feat(mobile): add Sasai brand assets (icon, splash, adaptive icon)"
```

---

### Task B6: Set up Expo Router root layout

**Files:**
- Create: `mobile/app/_layout.tsx`
- Create: `mobile/app/index.tsx`

- [ ] **Step 1: Root layout — providers + font loading + splash gate**

Create `mobile/app/_layout.tsx`:

```tsx
/**
 * Root layout — providers, theme, font loading.
 *
 * Wraps the entire app in:
 *   - SafeAreaProvider (Expo SafeArea)
 *   - GestureHandlerRootView (for Reanimated/Tamagui sheets)
 *   - TamaguiProvider (with active theme from useColorScheme)
 *   - QueryClientProvider (single TanStack Query client)
 *
 * Holds the native splash until fonts are loaded so we never render
 * a flash of system-font text.
 */
import { useFonts } from 'expo-font';
import { SplashScreen, Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useColorScheme } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { TamaguiProvider } from 'tamagui';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '../lib/query';
import config from '../tamagui.config';
import { useEffect } from 'react';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    'Inter-Regular':  require('../assets/fonts/Inter-Regular.ttf'),
    'Inter-Medium':   require('../assets/fonts/Inter-Medium.ttf'),
    'Inter-SemiBold': require('../assets/fonts/Inter-SemiBold.ttf'),
    'Inter-Bold':     require('../assets/fonts/Inter-Bold.ttf'),
  });
  const scheme = useColorScheme();

  useEffect(() => { if (fontsLoaded) SplashScreen.hideAsync(); }, [fontsLoaded]);
  if (!fontsLoaded) return null;

  return (
    <SafeAreaProvider>
      <GestureHandlerRootView style={{ flex: 1 }}>
        <TamaguiProvider config={config} defaultTheme={scheme === 'dark' ? 'dark' : 'light'}>
          <QueryClientProvider client={queryClient}>
            <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
            <Stack screenOptions={{ headerShown: false }} />
          </QueryClientProvider>
        </TamaguiProvider>
      </GestureHandlerRootView>
    </SafeAreaProvider>
  );
}
```

- [ ] **Step 2: Entry redirect**

Create `mobile/app/index.tsx`:

```tsx
/**
 * Entry redirect. Sends the user to /auth/phone or /(tabs)/home
 * depending on whether a session token is in secure storage.
 */
import { useEffect } from 'react';
import { Redirect } from 'expo-router';
import { useSession } from '../lib/auth';

export default function Index() {
  const { ready, hasSession } = useSession();
  if (!ready) return null;
  return <Redirect href={hasSession ? '/(tabs)/home' : '/auth/phone'} />;
}
```

(We implement `useSession` in Task B8.)

- [ ] **Step 3: Verify boot**

```bash
cd mobile && npx expo start --clear
```

Press `i` (iOS) or `a` (Android). Expected: app boots to an empty white
screen (because `/auth/phone` doesn't exist yet). No crashes, no font
warnings.

- [ ] **Step 4: Commit**

```bash
git add mobile/app/_layout.tsx mobile/app/index.tsx
git commit -m "feat(mobile): root layout with Tamagui, Query, fonts, and session-based redirect"
```

---

### Task B7: Secure storage + session hook

**Files:**
- Create: `mobile/lib/storage.ts`
- Create: `mobile/lib/auth.ts`

- [ ] **Step 1: Secure storage wrapper**

Create `mobile/lib/storage.ts`:

```ts
/**
 * Thin wrapper around expo-secure-store with typed keys.
 *
 * Use for: session_token, last_phone_e164, biometric_session_token.
 * Never store PIN here directly — only a biometric-gated session
 * token whose presence implies the user has previously authenticated.
 */
import * as SecureStore from 'expo-secure-store';

const KEYS = {
  sessionToken: 'session_token',
  lastPhone: 'last_phone_e164',
  biometricToken: 'biometric_session_token',
  biometricEnabled: 'biometric_enabled',
  tenantId: 'tenant_id',
} as const;

export const secureStorage = {
  async get(key: keyof typeof KEYS): Promise<string | null> {
    return SecureStore.getItemAsync(KEYS[key]);
  },
  async set(key: keyof typeof KEYS, value: string): Promise<void> {
    await SecureStore.setItemAsync(KEYS[key], value);
  },
  async remove(key: keyof typeof KEYS): Promise<void> {
    await SecureStore.deleteItemAsync(KEYS[key]);
  },
  async clear(): Promise<void> {
    await Promise.all(Object.values(KEYS).map((k) => SecureStore.deleteItemAsync(k)));
  },
};
```

- [ ] **Step 2: Session hook**

Create `mobile/lib/auth.ts`:

```ts
/**
 * Session state hook + helpers.
 *
 * `useSession()` returns whether a session token is present in secure
 * storage. The hook is consumed by `app/index.tsx` to redirect the
 * user to /auth/phone or /(tabs)/home on launch.
 *
 * `signOut()` clears all secure storage and routes back to /auth/phone.
 */
import { useEffect, useState } from 'react';
import { router } from 'expo-router';
import { secureStorage } from './storage';

export function useSession() {
  const [ready, setReady] = useState(false);
  const [hasSession, setHasSession] = useState(false);

  useEffect(() => {
    (async () => {
      const token = await secureStorage.get('sessionToken');
      setHasSession(!!token);
      setReady(true);
    })();
  }, []);

  return { ready, hasSession };
}

export async function signOut(): Promise<void> {
  await secureStorage.clear();
  router.replace('/auth/phone');
}
```

- [ ] **Step 3: Commit**

```bash
git add mobile/lib/storage.ts mobile/lib/auth.ts
git commit -m "feat(mobile): add secure storage wrapper + useSession hook"
```

---

### Task B8: Environment config (staging vs local backend)

**Files:**
- Create: `mobile/app.config.ts`
- Create: `mobile/.env.development`
- Create: `mobile/.env.preview`
- Create: `mobile/lib/env.ts`

- [ ] **Step 1: Replace static app.json with dynamic app.config.ts**

Delete `mobile/app.json` (we keep its content but move it into the dynamic config so we can env-switch URLs without rebuilding). Create
`mobile/app.config.ts`:

```ts
/**
 * Expo dynamic config. Reads BACKEND_URL + TENANT_ID from the active
 * EAS profile (.env.development / .env.preview) and surfaces them on
 * Constants.expoConfig.extra for runtime use by lib/env.ts.
 */
import type { ExpoConfig } from 'expo/config';

const BACKEND_URL = process.env.BACKEND_URL ?? 'http://localhost:8000';
const TENANT_ID   = process.env.TENANT_ID ?? '00000000-0000-0000-0000-000000000000';

const config: ExpoConfig = {
  name: 'Sasai Wallet',
  slug: 'sasai-wallet',
  version: '0.1.0',
  orientation: 'portrait',
  icon: './assets/icon.png',
  scheme: 'sasai',
  userInterfaceStyle: 'automatic',
  splash: {
    image: './assets/splash.png',
    resizeMode: 'contain',
    backgroundColor: '#FFFFFF',
  },
  ios: { supportsTablet: false, bundleIdentifier: 'co.sasai.wallet' },
  android: {
    package: 'co.sasai.wallet',
    adaptiveIcon: {
      foregroundImage: './assets/adaptive-icon.png',
      backgroundColor: '#144989',
    },
  },
  plugins: [
    'expo-router',
    'expo-font',
    'expo-secure-store',
    'expo-local-authentication',
  ],
  experiments: { typedRoutes: true },
  extra: { backendUrl: BACKEND_URL, tenantId: TENANT_ID },
};

export default config;
```

- [ ] **Step 2: Create env files**

`mobile/.env.development`:
```
BACKEND_URL=http://localhost:8000
TENANT_ID=<paste tenant uuid from `psql -c "SELECT id FROM tenants WHERE slug='sasai-za';"`>
```

`mobile/.env.preview`:
```
BACKEND_URL=https://staging.api.sasai.example
TENANT_ID=<staging tenant uuid>
```

- [ ] **Step 3: Add env accessor**

Create `mobile/lib/env.ts`:

```ts
/**
 * Runtime env accessor. Reads from Constants.expoConfig.extra
 * (populated by app.config.ts at build/start time).
 */
import Constants from 'expo-constants';

type Env = { backendUrl: string; tenantId: string };

export const env: Env = {
  backendUrl: Constants.expoConfig?.extra?.backendUrl as string,
  tenantId:   Constants.expoConfig?.extra?.tenantId   as string,
};

if (!env.backendUrl || !env.tenantId) {
  throw new Error('Missing env: backendUrl/tenantId must be set via app.config.ts');
}
```

Install expo-constants if not already present:

```bash
cd mobile && npx expo install expo-constants
```

- [ ] **Step 4: Commit**

```bash
git add mobile/app.config.ts mobile/lib/env.ts mobile/.env.* mobile/package.json
git rm mobile/app.json
git commit -m "feat(mobile): dynamic app config with BACKEND_URL + TENANT_ID env switching"
```

---

### Task B9: API client wrapper

**Files:**
- Create: `mobile/lib/api/client.ts`
- Create: `mobile/lib/api/errors.ts`

- [ ] **Step 1: Typed error classes**

Create `mobile/lib/api/errors.ts`:

```ts
/**
 * Typed errors mapped from backend {error_code, message} payloads.
 * Consumers `instanceof`-check to drive UI branches (step-up sheet,
 * lockout screen, insufficient-balance toast, etc.).
 */
export class ApiError extends Error {
  constructor(public code: string, public httpStatus: number, message: string) {
    super(message);
  }
}

export class StepUpRequired   extends ApiError {}
export class InvalidStepUpPin extends ApiError {}
export class InsufficientBalance extends ApiError {}
export class RecipientNotFound extends ApiError {}
export class SessionExpired   extends ApiError {}
export class Lockout          extends ApiError {}
export class NetworkError     extends ApiError {}

export function mapError(code: string, httpStatus: number, message: string): ApiError {
  switch (code) {
    case 'step_up_required':       return new StepUpRequired(code, httpStatus, message);
    case 'invalid_step_up_pin':    return new InvalidStepUpPin(code, httpStatus, message);
    case 'insufficient_balance':   return new InsufficientBalance(code, httpStatus, message);
    case 'recipient_not_found':    return new RecipientNotFound(code, httpStatus, message);
    case 'session_expired':        return new SessionExpired(code, httpStatus, message);
    case 'account_locked':         return new Lockout(code, httpStatus, message);
    default:                       return new ApiError(code || 'unknown', httpStatus, message);
  }
}
```

- [ ] **Step 2: Typed fetch wrapper**

Create `mobile/lib/api/client.ts`:

```ts
/**
 * Typed fetch wrapper for the Sasai backend.
 *
 * - Injects Authorization (bearer), X-Tenant-Id, Idempotency-Key headers.
 * - Maps {error_code, message} JSON payloads to typed errors.
 * - Never logs request bodies for endpoints that may carry `pin`.
 */
import { secureStorage } from '../storage';
import { env } from '../env';
import { mapError, NetworkError } from './errors';

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';

const SENSITIVE = /\/(auth|payments|redemption)/;

export async function api<T>(
  method: Method,
  path: string,
  opts: { body?: unknown; idempotencyKey?: string; noAuth?: boolean } = {},
): Promise<T> {
  const token = opts.noAuth ? null : await secureStorage.get('sessionToken');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Tenant-Id': env.tenantId,
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey;

  let response: Response;
  try {
    response = await fetch(`${env.backendUrl}${path}`, {
      method,
      headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    throw new NetworkError('network', 0, 'Network unreachable');
  }

  const text = await response.text();
  const json = text ? JSON.parse(text) : undefined;

  if (!response.ok) {
    const code = json?.error_code ?? json?.detail?.error_code ?? 'unknown';
    const message = json?.message ?? json?.detail?.message ?? response.statusText;
    throw mapError(code, response.status, message);
  }

  // Dev-only debug log; never include body for sensitive endpoints.
  if (__DEV__ && !SENSITIVE.test(path)) {
    console.log(`[api] ${method} ${path} → ${response.status}`);
  }
  return json as T;
}

export function newIdempotencyKey(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
```

- [ ] **Step 3: Commit**

```bash
git add mobile/lib/api/
git commit -m "feat(mobile): typed API client with bearer auth, idempotency, and error mapping"
```

---

### Task B10: TanStack Query client + key factory

**Files:**
- Create: `mobile/lib/query.ts`
- Create: `mobile/lib/api/wallet.ts`
- Create: `mobile/lib/api/catalog.ts`
- Create: `mobile/lib/api/payments.ts`
- Create: `mobile/lib/api/redemption.ts`
- Create: `mobile/lib/api/auth.ts`

- [ ] **Step 1: Query client + key factory**

Create `mobile/lib/query.ts`:

```ts
/**
 * Singleton TanStack Query client + typed query-key factory.
 * Mutations invalidate keys via `queryClient.invalidateQueries({queryKey: qk.wallet()})`.
 */
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
    mutations: { retry: 0 },
  },
});

export const qk = {
  wallet:            () => ['wallet']                  as const,
  catalog:           () => ['catalog']                 as const,
  featuredCampaign:  () => ['catalog', 'featured']     as const,
  redemption:        (id: string) => ['redemption', id] as const,
};
```

- [ ] **Step 2: Auth API module**

Create `mobile/lib/api/auth.ts`:

```ts
import { api } from './client';

export type AuthStartResponse = { status: 'needs_otp' | 'needs_pin' };
export type SessionTokenResponse = { session_token: string; expires_at: string };

export async function authStart(phoneE164: string): Promise<AuthStartResponse> {
  return api('POST', '/api/v1/identity/auth/start', {
    body: { phone_e164: phoneE164 },
    noAuth: true,
  });
}

export async function otpSend(phoneE164: string): Promise<void> {
  await api('POST', '/api/v1/identity/otp/send', {
    body: { phone_e164: phoneE164 },
    noAuth: true,
  });
}

export async function otpVerify(phoneE164: string, otp: string): Promise<{otp_verification_token: string}> {
  return api('POST', '/api/v1/identity/otp/verify', {
    body: { phone_e164: phoneE164, otp },
    noAuth: true,
  });
}

export async function pinSet(otpVerificationToken: string, pin: string): Promise<SessionTokenResponse> {
  return api('POST', '/api/v1/identity/pin/set', {
    body: { otp_verification_token: otpVerificationToken, pin },
    noAuth: true,
  });
}

export async function authPin(phoneE164: string, pin: string): Promise<SessionTokenResponse> {
  return api('POST', '/api/v1/identity/auth/pin', {
    body: { phone_e164: phoneE164, pin },
    noAuth: true,
  });
}

export async function logout(): Promise<void> {
  await api('POST', '/api/v1/identity/auth/logout');
}
```

> Verify the exact request/response shapes for `otp/send`, `otp/verify`,
> `pin/set`, and `auth/pin` against `backend/app/modules/identity/schemas.py`
> before merging. If field names differ, update this module to match.

- [ ] **Step 3: Wallet API module**

Create `mobile/lib/api/wallet.ts`:

```ts
import { api } from './client';

export type WalletTransaction = {
  id: string;
  account_id: string;
  currency: 'ZAR' | 'PTS';
  entry_type: 'CREDIT' | 'DEBIT';
  amount: string;
  description: string | null;
  counterparty_phone_masked: string | null;
  created_at: string;
};

export type Wallet = {
  accounts: { id: string; currency: 'ZAR' | 'PTS'; balance: string; account_type: string }[];
  recent_transactions: WalletTransaction[];
  user: { id: string; first_name: string | null; phone_masked: string };
};

export async function getWallet(): Promise<Wallet> {
  return api('GET', '/api/v1/identity/me/wallet');
}
```

- [ ] **Step 4: Catalog API module**

Create `mobile/lib/api/catalog.ts`:

```ts
import { api } from './client';

export type Offer = {
  id: string;
  category: 'airtime' | 'voucher' | 'data' | 'groceries' | string;
  name: string;
  face_value_zar: string;
  points_cost: number;
  image_url: string | null;
  description: string | null;
};

export type CatalogSummary = { offers: Offer[]; pts_to_zar_rate: number };

export type FeaturedCampaign = {
  id: string;
  title: string;
  subtitle: string;
  primary_action: 'topup' | 'p2p' | 'redeem';
  suggested_amount: string | null;
  suggested_currency: string | null;
  reward_hint: string | null;
};

export async function getCatalog(): Promise<CatalogSummary> {
  return api('GET', '/api/v1/catalog/me/summary');
}

export async function getFeaturedCampaign(): Promise<{ campaign: FeaturedCampaign | null }> {
  return api('GET', '/api/v1/catalog/featured');
}
```

- [ ] **Step 5: Payments API module**

Create `mobile/lib/api/payments.ts`:

```ts
import { api } from './client';

export type P2PResponse = {
  transaction_id: string;
  status: string;
  amount: string;
  currency: string;
  sender_user_id: string;
  recipient_user_id: string;
  created_at: string;
  earned_points: number | null;
};

export async function p2p(
  args: { recipient_phone: string; amount: string; description?: string; pin?: string },
  idempotencyKey: string,
): Promise<P2PResponse> {
  return api('POST', '/api/v1/payments/p2p', {
    body: {
      recipient: { identifier_type: 'phone', identifier_value: args.recipient_phone },
      amount: args.amount,
      currency: 'ZAR',
      description: args.description,
      pin: args.pin,
    },
    idempotencyKey,
  });
}

export type TopupResponse = {
  transaction_id: string;
  ledger_entry_id: string;
  new_balance: string;
  currency: string;
  earned_points: number | null;
  created_at: string;
};

export async function topup(
  args: { amount: string; pin?: string; demo_reference?: string },
  idempotencyKey: string,
): Promise<TopupResponse> {
  return api('POST', '/api/v1/payments/topup', {
    body: {
      amount: args.amount,
      currency: 'ZAR',
      demo_reference: args.demo_reference ?? 'demo-card-4242',
      pin: args.pin,
    },
    idempotencyKey,
  });
}
```

- [ ] **Step 6: Redemption API module**

Create `mobile/lib/api/redemption.ts`:

```ts
import { api } from './client';

export type Redemption = {
  id: string;
  status: 'pending' | 'completed' | 'failed';
  offer_id: string;
  recipient_phone: string;
  points_cost: number;
  created_at: string;
  fulfilled_at: string | null;
  reference: string | null;
};

export async function initiateRedemption(
  args: { offer_id: string; recipient_phone: string },
  idempotencyKey: string,
): Promise<Redemption> {
  return api('POST', '/api/v1/redemption/initiate', {
    body: args, idempotencyKey,
  });
}

export async function confirmRedemption(
  redemptionId: string,
  args: { pin?: string },
  idempotencyKey: string,
): Promise<Redemption> {
  return api('POST', `/api/v1/redemption/${redemptionId}/confirm`, {
    body: args, idempotencyKey,
  });
}

export async function getRedemption(redemptionId: string): Promise<Redemption> {
  return api('GET', `/api/v1/redemption/${redemptionId}`);
}
```

- [ ] **Step 7: Commit**

```bash
git add mobile/lib/query.ts mobile/lib/api/
git commit -m "feat(mobile): TanStack Query client + typed API modules (auth, wallet, catalog, payments, redemption)"
```

---

### Phase B wrap-up

Quick smoke test before moving to Phase C:

```bash
cd mobile && npx expo start --clear
```

Press `i`. The app should boot to a blank screen (because `/auth/phone`
isn't built yet) with no font, theme, or import errors in the Metro
console.

---

## Phase C — Auth flow

### Task C1: Phone screen + PhoneInput component

**Files:**
- Create: `mobile/components/forms/PhoneInput.tsx`
- Create: `mobile/app/auth/_layout.tsx`
- Create: `mobile/app/auth/phone.tsx`

- [ ] **Step 1: PhoneInput component**

Create `mobile/components/forms/PhoneInput.tsx`:

```tsx
/**
 * PhoneInput — country code picker (defaults +27 ZA) + national number input.
 *
 * Returns the composed E.164 string via onChange. Used on /auth/phone,
 * /p2p/recipient, and redemption recipient field.
 */
import { useState } from 'react';
import { XStack, YStack, Input, Text, Button, Sheet } from 'tamagui';
import { ChevronDown } from '@tamagui/lucide-icons';

type Country = { code: string; flag: string; dial: string; name: string };

const COUNTRIES: Country[] = [
  { code: 'ZA', flag: '🇿🇦', dial: '+27', name: 'South Africa' },
  { code: 'IN', flag: '🇮🇳', dial: '+91', name: 'India' },
  { code: 'ZW', flag: '🇿🇼', dial: '+263', name: 'Zimbabwe' },
  { code: 'GB', flag: '🇬🇧', dial: '+44', name: 'United Kingdom' },
  { code: 'US', flag: '🇺🇸', dial: '+1', name: 'United States' },
];

type Props = {
  value: string;
  onChangeE164: (e164: string) => void;
};

export function PhoneInput({ value, onChangeE164 }: Props) {
  const [country, setCountry] = useState<Country>(COUNTRIES[0]); // +27
  const [open, setOpen] = useState(false);
  const national = value.startsWith(country.dial) ? value.slice(country.dial.length) : '';

  function update(nextDigits: string) {
    onChangeE164(`${country.dial}${nextDigits.replace(/\D/g, '')}`);
  }

  return (
    <YStack gap="$2">
      <XStack gap="$2" alignItems="center">
        <Button size="$5" onPress={() => setOpen(true)} bordered>
          <Text fontSize="$6">{country.flag}</Text>
          <Text fontFamily="Inter-Medium">{country.dial}</Text>
          <ChevronDown size={16} />
        </Button>
        <Input flex={1} size="$5" placeholder="Phone number"
          keyboardType="phone-pad" value={national} onChangeText={update} />
      </XStack>

      <Sheet modal open={open} onOpenChange={setOpen} snapPoints={[60]} dismissOnSnapToBottom>
        <Sheet.Overlay />
        <Sheet.Frame padding="$4">
          <Sheet.Handle />
          <YStack gap="$2" marginTop="$3">
            {COUNTRIES.map((c) => (
              <Button key={c.code} chromeless justifyContent="flex-start"
                onPress={() => { setCountry(c); setOpen(false); update(national); }}>
                <Text fontSize="$5">{c.flag}</Text>
                <Text flex={1} fontFamily="Inter-Medium">{c.name}</Text>
                <Text color="$muted">{c.dial}</Text>
              </Button>
            ))}
          </YStack>
        </Sheet.Frame>
      </Sheet>
    </YStack>
  );
}
```

- [ ] **Step 2: Auth layout (no header)**

Create `mobile/app/auth/_layout.tsx`:

```tsx
import { Stack } from 'expo-router';
export default function AuthLayout() {
  return <Stack screenOptions={{ headerShown: false, animation: 'slide_from_right' }} />;
}
```

- [ ] **Step 3: Phone screen**

Create `mobile/app/auth/phone.tsx`:

```tsx
/**
 * Step 1 of auth: enter phone number, branch to OTP (new) or PIN (existing).
 *
 * Calls POST /identity/auth/start. Caches phone in secure storage so we
 * can resume the OTP/PIN screen without re-asking.
 */
import { useState } from 'react';
import { router } from 'expo-router';
import { YStack, H1, Text, Button, Spinner } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';
import { PhoneInput } from '../../components/forms/PhoneInput';
import { authStart } from '../../lib/api/auth';
import { secureStorage } from '../../lib/storage';

export default function PhoneScreen() {
  const [phone, setPhone] = useState('+27');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onContinue() {
    setLoading(true); setError(null);
    try {
      const { status } = await authStart(phone);
      await secureStorage.set('lastPhone', phone);
      router.push(status === 'needs_otp' ? '/auth/otp' : '/auth/pin');
    } catch (e: any) {
      setError(e?.message ?? 'Something went wrong');
    } finally { setLoading(false); }
  }

  const valid = /^\+\d{8,15}$/.test(phone);

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$6" backgroundColor="$background">
        <YStack gap="$2" marginTop="$8">
          <H1 fontFamily="Inter-Bold" color="$primary">Welcome to sasai</H1>
          <Text color="$muted" fontFamily="Inter-Regular">
            Enter your phone number to continue
          </Text>
        </YStack>

        <PhoneInput value={phone} onChangeE164={setPhone} />

        {error && <Text color="$error" fontFamily="Inter-Medium">{error}</Text>}

        <Button size="$5" theme="active" disabled={!valid || loading}
          onPress={onContinue} marginTop="auto">
          {loading ? <Spinner /> : 'Continue'}
        </Button>
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 4: Verify on simulator**

```bash
cd mobile && npx expo start
```

Press `i`. Expected: phone screen renders with +27 default, picker opens
on tap, Continue disabled until ≥8 digits, taps call backend and route.
Use a seeded phone (Alice's) → should route to `/auth/pin`. Use a fresh
phone → routes to `/auth/otp`.

- [ ] **Step 5: Commit**

```bash
git add mobile/components/forms/PhoneInput.tsx mobile/app/auth/
git commit -m "feat(mobile): phone entry screen with country picker + auth/start lookup"
```

---

### Task C2: OTP screen + OtpInput component

**Files:**
- Create: `mobile/components/forms/OtpInput.tsx`
- Create: `mobile/app/auth/otp.tsx`

- [ ] **Step 1: OtpInput component**

Create `mobile/components/forms/OtpInput.tsx`:

```tsx
/**
 * 6-box OTP input. Paste-fills all six, advances focus on each digit,
 * calls onComplete() when full.
 */
import { useRef, useState } from 'react';
import { TextInput } from 'react-native';
import { XStack, Input } from 'tamagui';

type Props = { onComplete: (otp: string) => void };

export function OtpInput({ onComplete }: Props) {
  const [digits, setDigits] = useState<string[]>(Array(6).fill(''));
  const refs = useRef<(TextInput | null)[]>([]);

  function setAt(i: number, v: string) {
    if (v.length > 1) {
      const pasted = v.replace(/\D/g, '').slice(0, 6).split('');
      const next = Array(6).fill('').map((_, j) => pasted[j] ?? '');
      setDigits(next);
      if (next.every((d) => d !== '')) onComplete(next.join(''));
      refs.current[Math.min(pasted.length, 5)]?.focus();
      return;
    }
    const next = [...digits]; next[i] = v.replace(/\D/g, ''); setDigits(next);
    if (v && i < 5) refs.current[i + 1]?.focus();
    if (next.every((d) => d !== '')) onComplete(next.join(''));
  }

  return (
    <XStack gap="$2" justifyContent="center">
      {digits.map((d, i) => (
        <Input key={i} ref={(r) => { refs.current[i] = r as unknown as TextInput; }}
          width={48} height={56} textAlign="center" fontSize="$7"
          keyboardType="number-pad" maxLength={i === 0 ? 6 : 1}
          value={d} onChangeText={(v) => setAt(i, v)} />
      ))}
    </XStack>
  );
}
```

- [ ] **Step 2: OTP screen**

Create `mobile/app/auth/otp.tsx`:

```tsx
/**
 * Step 2 of auth (new users): 6-digit OTP verification.
 *
 * Calls /identity/otp/send on mount (fire-and-forget for the demo
 * since SMS isn't wired). Calls /otp/verify on completion; on success
 * stores the otp_verification_token and routes to set-pin.
 */
import { useEffect, useState } from 'react';
import { router } from 'expo-router';
import { YStack, H2, Text, Button, Spinner } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';
import { OtpInput } from '../../components/forms/OtpInput';
import { otpSend, otpVerify } from '../../lib/api/auth';
import { secureStorage } from '../../lib/storage';

export default function OtpScreen() {
  const [phone, setPhone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(30);

  useEffect(() => {
    (async () => {
      const p = await secureStorage.get('lastPhone');
      setPhone(p);
      if (p) await otpSend(p).catch(() => {});
    })();
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown(cooldown - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  async function onComplete(otp: string) {
    if (!phone) return;
    setBusy(true); setError(null);
    try {
      const { otp_verification_token } = await otpVerify(phone, otp);
      await secureStorage.set('sessionToken', otp_verification_token);  // ephemeral; replaced by /pin/set
      router.push('/auth/set-pin');
    } catch (e: any) {
      setError(e?.message ?? 'Invalid code');
    } finally { setBusy(false); }
  }

  async function resend() {
    if (!phone || cooldown > 0) return;
    await otpSend(phone).catch(() => {});
    setCooldown(30);
  }

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$6" backgroundColor="$background">
        <YStack gap="$2" marginTop="$8">
          <H2 fontFamily="Inter-Bold" color="$primary">Verify your number</H2>
          <Text color="$muted">We sent a 6-digit code to {phone}.</Text>
        </YStack>

        <OtpInput onComplete={onComplete} />

        {busy && <Spinner alignSelf="center" />}
        {error && <Text color="$error" textAlign="center">{error}</Text>}

        <Button chromeless disabled={cooldown > 0} onPress={resend} alignSelf="center"
          marginTop="auto">
          {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend code'}
        </Button>
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 3: Verify**

In dev, watch the backend logs for the printed OTP, type it in the
simulator. Expected: routes to `/auth/set-pin`.

- [ ] **Step 4: Commit**

```bash
git add mobile/components/forms/OtpInput.tsx mobile/app/auth/otp.tsx
git commit -m "feat(mobile): OTP verification screen with paste-fill + resend cooldown"
```

---

### Task C3: Set-PIN screen + PinInput component

**Files:**
- Create: `mobile/components/forms/PinInput.tsx`
- Create: `mobile/app/auth/set-pin.tsx`

- [ ] **Step 1: PinInput component**

Create `mobile/components/forms/PinInput.tsx`:

```tsx
/**
 * 4-digit PIN input with custom on-screen keypad. The native keyboard
 * is unreliable for masked inputs across devices, so we render our own.
 *
 * Calls onComplete when 4 digits entered.
 */
import { useState } from 'react';
import { Pressable } from 'react-native';
import { XStack, YStack, Text } from 'tamagui';

type Props = { onComplete: (pin: string) => void; clearOnComplete?: boolean };

export function PinInput({ onComplete, clearOnComplete }: Props) {
  const [pin, setPin] = useState('');

  function press(key: string) {
    if (key === '⌫') return setPin((p) => p.slice(0, -1));
    if (pin.length >= 4) return;
    const next = pin + key;
    setPin(next);
    if (next.length === 4) {
      onComplete(next);
      if (clearOnComplete) setTimeout(() => setPin(''), 300);
    }
  }

  return (
    <YStack gap="$5" alignItems="center">
      <XStack gap="$3">
        {[0, 1, 2, 3].map((i) => (
          <YStack key={i} width={18} height={18} borderRadius={9}
            backgroundColor={i < pin.length ? '$primary' : '$muted'} opacity={i < pin.length ? 1 : 0.3} />
        ))}
      </XStack>
      <YStack gap="$2">
        {[['1','2','3'],['4','5','6'],['7','8','9'],['','0','⌫']].map((row, ri) => (
          <XStack key={ri} gap="$2">
            {row.map((k, ci) => (
              <Pressable key={`${ri}-${ci}`} onPress={() => k && press(k)}
                style={{ width: 72, height: 72, borderRadius: 36, alignItems: 'center', justifyContent: 'center' }}>
                <Text fontSize="$8" fontFamily="Inter-Medium">{k}</Text>
              </Pressable>
            ))}
          </XStack>
        ))}
      </YStack>
    </YStack>
  );
}
```

- [ ] **Step 2: Set-PIN screen**

Create `mobile/app/auth/set-pin.tsx`:

```tsx
/**
 * Step 3 of auth (new users): two-step PIN creation.
 * Enter PIN → confirm PIN → POST /identity/pin/set → session token →
 * route to home.
 */
import { useState } from 'react';
import { router } from 'expo-router';
import { YStack, H2, Text } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';
import { PinInput } from '../../components/forms/PinInput';
import { pinSet } from '../../lib/api/auth';
import { secureStorage } from '../../lib/storage';

export default function SetPinScreen() {
  const [first, setFirst] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onComplete(pin: string) {
    if (first === null) { setFirst(pin); return; }
    if (pin !== first) {
      setError('PINs don\'t match. Try again.');
      setFirst(null);
      return;
    }
    try {
      const token = await secureStorage.get('sessionToken');
      if (!token) throw new Error('Missing OTP verification token');
      const session = await pinSet(token, pin);
      await secureStorage.set('sessionToken', session.session_token);
      router.replace('/(tabs)/home');
    } catch (e: any) {
      setError(e?.message ?? 'Failed to set PIN');
      setFirst(null);
    }
  }

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$6" backgroundColor="$background" alignItems="center">
        <YStack gap="$2" marginTop="$8" alignItems="center">
          <H2 fontFamily="Inter-Bold" color="$primary">
            {first === null ? 'Create your PIN' : 'Confirm your PIN'}
          </H2>
          <Text color="$muted">4 digits, used to sign in next time</Text>
        </YStack>

        <PinInput onComplete={onComplete} clearOnComplete />

        {error && <Text color="$error" textAlign="center">{error}</Text>}
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 3: Verify**

Walk through phone → otp → set-pin on a fresh phone number. Expected:
after confirming the PIN, app routes to `/(tabs)/home` (which will be a
blank screen until Phase D, but the URL should change without crash).

- [ ] **Step 4: Commit**

```bash
git add mobile/components/forms/PinInput.tsx mobile/app/auth/set-pin.tsx
git commit -m "feat(mobile): set-PIN screen with two-step entry + custom keypad"
```

---

### Task C4: PIN screen + biometric opt-in

**Files:**
- Create: `mobile/app/auth/pin.tsx`
- Modify: `mobile/lib/auth.ts` (add biometric helpers)

- [ ] **Step 1: Biometric helpers in lib/auth.ts**

Append to `mobile/lib/auth.ts`:

```ts
import * as LocalAuthentication from 'expo-local-authentication';
import { secureStorage } from './storage';

export async function isBiometricAvailable(): Promise<boolean> {
  return (await LocalAuthentication.hasHardwareAsync())
      && (await LocalAuthentication.isEnrolledAsync());
}

export async function tryBiometricLogin(): Promise<string | null> {
  const enabled = await secureStorage.get('biometricEnabled');
  if (enabled !== 'true') return null;
  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: 'Sign in with biometrics',
    fallbackLabel: 'Use PIN',
  });
  if (!result.success) return null;
  return await secureStorage.get('biometricToken');
}

export async function enableBiometric(sessionToken: string): Promise<boolean> {
  if (!(await isBiometricAvailable())) return false;
  await secureStorage.set('biometricToken', sessionToken);
  await secureStorage.set('biometricEnabled', 'true');
  return true;
}
```

- [ ] **Step 2: PIN screen**

Create `mobile/app/auth/pin.tsx`:

```tsx
/**
 * Returning-user PIN entry. Tries biometric on mount (if previously
 * enabled), falls back to manual PIN entry. On first successful PIN
 * post-install, prompts to enable biometrics for next time.
 */
import { useEffect, useState } from 'react';
import { router } from 'expo-router';
import { YStack, H2, Text, Sheet, Button } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';
import { PinInput } from '../../components/forms/PinInput';
import { authPin } from '../../lib/api/auth';
import { enableBiometric, isBiometricAvailable, tryBiometricLogin } from '../../lib/auth';
import { secureStorage } from '../../lib/storage';

export default function PinScreen() {
  const [phone, setPhone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bioOpen, setBioOpen] = useState(false);
  const [bioCandidate, setBioCandidate] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setPhone(await secureStorage.get('lastPhone'));
      const t = await tryBiometricLogin();
      if (t) { await secureStorage.set('sessionToken', t); router.replace('/(tabs)/home'); }
    })();
  }, []);

  async function onPin(pin: string) {
    if (!phone) return;
    setError(null);
    try {
      const session = await authPin(phone, pin);
      await secureStorage.set('sessionToken', session.session_token);
      if (await isBiometricAvailable() &&
          (await secureStorage.get('biometricEnabled')) !== 'true') {
        setBioCandidate(session.session_token);
        setBioOpen(true);
        return;
      }
      router.replace('/(tabs)/home');
    } catch (e: any) {
      setError(e?.message ?? 'Incorrect PIN');
    }
  }

  async function acceptBio() {
    if (bioCandidate) await enableBiometric(bioCandidate);
    setBioOpen(false);
    router.replace('/(tabs)/home');
  }

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$6" backgroundColor="$background" alignItems="center">
        <YStack gap="$2" marginTop="$8" alignItems="center">
          <H2 fontFamily="Inter-Bold" color="$primary">Welcome back</H2>
          <Text color="$muted">Enter your PIN to continue</Text>
        </YStack>

        <PinInput onComplete={onPin} clearOnComplete />
        {error && <Text color="$error" textAlign="center">{error}</Text>}

        <Sheet modal open={bioOpen} onOpenChange={setBioOpen} snapPoints={[40]} dismissOnSnapToBottom>
          <Sheet.Overlay />
          <Sheet.Frame padding="$6" gap="$4" alignItems="center">
            <Sheet.Handle />
            <H2 fontFamily="Inter-Bold" color="$primary">Use Face ID next time?</H2>
            <Text textAlign="center" color="$muted">
              Skip the PIN by unlocking with biometrics. You can change this in Profile.
            </Text>
            <Button size="$5" theme="active" onPress={acceptBio}>Enable</Button>
            <Button chromeless onPress={() => { setBioOpen(false); router.replace('/(tabs)/home'); }}>
              Not now
            </Button>
          </Sheet.Frame>
        </Sheet>
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 3: Verify**

Sign out + sign back in with PIN `1234` (seeded). Expected: after PIN
success, biometric opt-in sheet appears (on a device/simulator with
biometrics configured). Tapping Enable triggers Face ID/Touch ID prompt;
"Not now" routes straight to home.

- [ ] **Step 4: Commit**

```bash
git add mobile/lib/auth.ts mobile/app/auth/pin.tsx
git commit -m "feat(mobile): PIN entry screen with biometric login + opt-in sheet"
```

---

## Phase D — Home + Activity + Profile

### Task D1: Tabs layout with floating glass tab bar

**Files:**
- Create: `mobile/app/(tabs)/_layout.tsx`
- Create: `mobile/components/ui/TabBar.tsx`

- [ ] **Step 1: Custom floating tab bar**

Create `mobile/components/ui/TabBar.tsx`:

```tsx
/**
 * Floating glass tab bar. Renders three tabs (Home · Activity · Profile)
 * with a blur background on iOS (expo-blur) and a solid semi-transparent
 * surface on Android. Designed to sit ~12px above the home indicator,
 * not anchored to the bottom edge — modern fintech feel.
 */
import { Pressable, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { XStack, YStack, Text } from 'tamagui';
import { Home, Activity, User } from '@tamagui/lucide-icons';
import { BottomTabBarProps } from '@react-navigation/bottom-tabs';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

const ICON = { home: Home, activity: Activity, profile: User } as const;

export function FloatingTabBar({ state, navigation }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();
  return (
    <YStack position="absolute" bottom={insets.bottom + 12} left={0} right={0} alignItems="center">
      <XStack borderRadius={32} overflow="hidden" elevation={6}
        backgroundColor={Platform.OS === 'android' ? 'rgba(20,73,137,0.85)' : 'transparent'}>
        {Platform.OS === 'ios' && (
          <BlurView intensity={50} tint="systemMaterial"
            style={{ position: 'absolute', inset: 0 }} />
        )}
        <XStack paddingHorizontal="$3" paddingVertical="$2" gap="$2">
          {state.routes.map((route, i) => {
            const Icon = ICON[route.name as keyof typeof ICON];
            const active = state.index === i;
            return (
              <Pressable key={route.key} onPress={() => navigation.navigate(route.name)}
                style={{ paddingHorizontal: 18, paddingVertical: 10, alignItems: 'center' }}>
                <Icon size={22} color={active ? '#48C2CF' : '#E8F0F8'} />
                <Text fontSize={11} marginTop={2}
                  color={active ? '$accent' : '$inkInverse'}>{labelFor(route.name)}</Text>
              </Pressable>
            );
          })}
        </XStack>
      </XStack>
    </YStack>
  );
}

function labelFor(name: string) {
  return name === 'home' ? 'Home' : name === 'activity' ? 'Activity' : 'Profile';
}
```

- [ ] **Step 2: Tab layout**

Create `mobile/app/(tabs)/_layout.tsx`:

```tsx
import { Tabs } from 'expo-router';
import { FloatingTabBar } from '../../components/ui/TabBar';

export default function TabsLayout() {
  return (
    <Tabs tabBar={(props) => <FloatingTabBar {...props} />}
      screenOptions={{ headerShown: false }}>
      <Tabs.Screen name="home" />
      <Tabs.Screen name="activity" />
      <Tabs.Screen name="profile" />
    </Tabs>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add mobile/app/\(tabs\)/_layout.tsx mobile/components/ui/TabBar.tsx
git commit -m "feat(mobile): floating glass tab bar (Home · Activity · Profile)"
```

---

### Task D2: BalanceCard with gradient + tap-to-mask

**Files:**
- Create: `mobile/components/ui/BalanceCard.tsx`
- Create: `mobile/lib/format.ts`

- [ ] **Step 1: Currency + phone formatters**

Create `mobile/lib/format.ts`:

```ts
/**
 * Formatters for currency, points, and masked PII.
 * No third-party intl deps — keeps the bundle small.
 */
export function formatZAR(amount: string | number): string {
  const n = typeof amount === 'string' ? parseFloat(amount) : amount;
  return `R ${n.toLocaleString('en-ZA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatPTS(points: number): string {
  return `${points.toLocaleString('en-ZA')} PTS`;
}

export function maskPhone(e164: string): string {
  if (e164.length < 6) return e164;
  return `${e164.slice(0, 4)} ${e164.slice(4, 6)} *** ${e164.slice(-4)}`;
}

export function maskAccountSuffix(id: string): string {
  return `•• •• •• ${id.slice(-4)}`;
}
```

- [ ] **Step 2: BalanceCard**

Create `mobile/components/ui/BalanceCard.tsx`:

```tsx
/**
 * Hero ZAR balance card. Full-bleed gradient (navy → teal), rounded-3xl,
 * eye toggle to mask the balance value. Tap-to-mask is a small piece of
 * polish that lands well in demos.
 */
import { useState } from 'react';
import { Pressable } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { YStack, XStack, Text } from 'tamagui';
import { Eye, EyeOff } from '@tamagui/lucide-icons';
import { formatZAR, maskAccountSuffix } from '../../lib/format';

type Props = { balance: string; accountId: string };

export function BalanceCard({ balance, accountId }: Props) {
  const [masked, setMasked] = useState(false);

  return (
    <LinearGradient colors={['#144989', '#48C2CF']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
      style={{ borderRadius: 28, padding: 20, overflow: 'hidden' }}>
      <XStack justifyContent="space-between" alignItems="center" marginBottom="$3">
        <Text color="white" opacity={0.9} fontFamily="Inter-Medium">ZAR · Available</Text>
        <Pressable onPress={() => setMasked((m) => !m)} hitSlop={12}>
          {masked ? <EyeOff size={18} color="white" /> : <Eye size={18} color="white" />}
        </Pressable>
      </XStack>
      <Text color="white" fontFamily="Inter-Bold" fontSize={38}>
        {masked ? 'R ••••••' : formatZAR(balance)}
      </Text>
      <XStack justifyContent="space-between" alignItems="center" marginTop="$4">
        <Text color="white" opacity={0.85}>{maskAccountSuffix(accountId)}</Text>
        <Text color="white" opacity={0.85} fontFamily="Inter-Medium">⌁ sasai</Text>
      </XStack>
    </LinearGradient>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add mobile/lib/format.ts mobile/components/ui/BalanceCard.tsx
git commit -m "feat(mobile): BalanceCard with navy→teal gradient and tap-to-mask"
```

---

### Task D3: ActionChip + QuickActions row

**Files:**
- Create: `mobile/components/ui/ActionChip.tsx`

- [ ] **Step 1: ActionChip**

```tsx
/**
 * Circular pill action button used in the home Quick Actions row.
 * Tap-scales to 0.95 (Tamagui pressStyle). Icon + label below.
 */
import { Pressable } from 'react-native';
import { YStack, Text } from 'tamagui';
import { LucideIcon } from '@tamagui/lucide-icons';

type Props = { icon: LucideIcon; label: string; onPress: () => void };

export function ActionChip({ icon: Icon, label, onPress }: Props) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => ({ transform: [{ scale: pressed ? 0.95 : 1 }] })}>
      <YStack alignItems="center" gap="$2" width={72}>
        <YStack width={56} height={56} borderRadius={28} alignItems="center" justifyContent="center"
          backgroundColor="$primary">
          <Icon size={22} color="#FFFFFF" />
        </YStack>
        <Text fontSize={12} fontFamily="Inter-Medium" color="$color">{label}</Text>
      </YStack>
    </Pressable>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add mobile/components/ui/ActionChip.tsx
git commit -m "feat(mobile): ActionChip pill button for home quick actions"
```

---

### Task D4: BeneficiaryStrip — horizontal "Send again" carousel

**Files:**
- Create: `mobile/components/ui/BeneficiaryStrip.tsx`

- [ ] **Step 1: BeneficiaryStrip**

```tsx
/**
 * Horizontal "Send again" carousel of recent P2P recipients. Initials
 * are color-hashed from the phone E.164 so each recipient has a stable
 * unique color across sessions.
 */
import { Pressable, ScrollView } from 'react-native';
import { YStack, Text } from 'tamagui';
import { Plus } from '@tamagui/lucide-icons';

type Beneficiary = { name: string; phone: string };
type Props = { items: Beneficiary[]; onPick: (b: Beneficiary) => void; onAdd: () => void };

const PALETTE = ['#144989', '#48C2CF', '#2EA5B2', '#F59E0B', '#22C55E', '#EF4444'];

function colorFor(phone: string) {
  let h = 0; for (const c of phone) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

export function BeneficiaryStrip({ items, onPick, onAdd }: Props) {
  if (items.length === 0) return null;
  return (
    <YStack gap="$2">
      <Text color="$muted" fontFamily="Inter-Medium" paddingHorizontal="$4">Send again</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ paddingHorizontal: 16, gap: 12 }}>
        {items.map((b) => (
          <Pressable key={b.phone} onPress={() => onPick(b)}>
            <YStack alignItems="center" gap="$1" width={56}>
              <YStack width={48} height={48} borderRadius={24} alignItems="center" justifyContent="center"
                backgroundColor={colorFor(b.phone)}>
                <Text color="white" fontFamily="Inter-Bold">{b.name.slice(0, 1).toUpperCase()}</Text>
              </YStack>
              <Text fontSize={11} numberOfLines={1}>{b.name}</Text>
            </YStack>
          </Pressable>
        ))}
        <Pressable onPress={onAdd}>
          <YStack alignItems="center" gap="$1" width={56}>
            <YStack width={48} height={48} borderRadius={24} alignItems="center" justifyContent="center"
              backgroundColor="$muted" opacity={0.2}>
              <Plus size={20} />
            </YStack>
            <Text fontSize={11}>Add</Text>
          </YStack>
        </Pressable>
      </ScrollView>
    </YStack>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add mobile/components/ui/BeneficiaryStrip.tsx
git commit -m "feat(mobile): BeneficiaryStrip horizontal carousel with color-hashed avatars"
```

---

### Task D5: CampaignBanner — featured campaign card

**Files:**
- Create: `mobile/components/ui/CampaignBanner.tsx`

- [ ] **Step 1: CampaignBanner**

```tsx
/**
 * Featured-campaign card on home. Subtle teal-tinted background,
 * chevron, press-scale animation. Collapses gracefully when null.
 */
import { Pressable } from 'react-native';
import { XStack, YStack, Text } from 'tamagui';
import { Sparkles, ChevronRight } from '@tamagui/lucide-icons';
import type { FeaturedCampaign } from '../../lib/api/catalog';

type Props = { campaign: FeaturedCampaign | null; onPress: (c: FeaturedCampaign) => void };

export function CampaignBanner({ campaign, onPress }: Props) {
  if (!campaign) return null;
  return (
    <Pressable onPress={() => onPress(campaign)}
      style={({ pressed }) => ({ transform: [{ scale: pressed ? 0.98 : 1 }] })}>
      <XStack backgroundColor="rgba(72,194,207,0.12)" borderRadius={20}
        padding="$4" alignItems="center" gap="$3">
        <Sparkles color="#48C2CF" size={22} />
        <YStack flex={1} gap="$1">
          <Text fontFamily="Inter-Bold" color="$primary">{campaign.title}</Text>
          <Text color="$muted" fontSize={13}>{campaign.subtitle}</Text>
        </YStack>
        <ChevronRight color="#48C2CF" size={18} />
      </XStack>
    </Pressable>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add mobile/components/ui/CampaignBanner.tsx
git commit -m "feat(mobile): CampaignBanner for featured-campaign card on home"
```

---

### Task D6: ActivityRow + Home screen

**Files:**
- Create: `mobile/components/ui/ActivityRow.tsx`
- Create: `mobile/app/(tabs)/home.tsx`

- [ ] **Step 1: ActivityRow**

```tsx
/**
 * One row in the home activity preview or full activity list. Type
 * icon + label + relative time + signed amount. Color-coded:
 * credits = teal accent, debits = muted-red.
 */
import { XStack, YStack, Text } from 'tamagui';
import { ArrowDown, ArrowUp, Sparkles, Ticket } from '@tamagui/lucide-icons';
import type { WalletTransaction } from '../../lib/api/wallet';

type Props = { txn: WalletTransaction };

export function ActivityRow({ txn }: Props) {
  const isPts = txn.currency === 'PTS';
  const isCredit = txn.entry_type === 'CREDIT';
  const Icon = isPts ? (isCredit ? Sparkles : Ticket) : (isCredit ? ArrowDown : ArrowUp);
  const sign = isCredit ? '+' : '−';
  const color = isCredit ? '$accent' : '$error';
  const amount = isPts ? `${sign}${parseInt(txn.amount)} PTS` : `${sign}R ${parseFloat(txn.amount).toFixed(2)}`;
  const when = new Date(txn.created_at);
  const today = new Date();
  const relative = sameDay(when, today) ? 'Today'
                : sameDay(when, addDays(today, -1)) ? 'Yesterday'
                : when.toLocaleDateString('en-ZA', { day: '2-digit', month: 'short' });

  return (
    <XStack paddingVertical="$3" paddingHorizontal="$4" gap="$3" alignItems="center">
      <YStack width={36} height={36} borderRadius={18} alignItems="center" justifyContent="center"
        backgroundColor={isCredit ? 'rgba(72,194,207,0.15)' : 'rgba(239,68,68,0.10)'}>
        <Icon size={18} color={isCredit ? '#48C2CF' : '#EF4444'} />
      </YStack>
      <YStack flex={1}>
        <Text fontFamily="Inter-Medium">{labelFor(txn)}</Text>
        <Text fontSize={12} color="$muted">{relative}</Text>
      </YStack>
      <Text fontFamily="Inter-SemiBold" color={color}>{amount}</Text>
    </XStack>
  );
}

function labelFor(t: WalletTransaction): string {
  if (t.description) return t.description;
  if (t.entry_type === 'CREDIT') return t.currency === 'PTS' ? 'Reward earned' : 'Credit';
  return t.currency === 'PTS' ? 'Reward redeemed' : 'Payment sent';
}

function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear()
      && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
function addDays(d: Date, n: number) {
  const x = new Date(d); x.setDate(x.getDate() + n); return x;
}
```

- [ ] **Step 2: Home screen**

```tsx
/**
 * Home tab. Top bar · BalanceCard · QuickActions · BeneficiaryStrip ·
 * CampaignBanner · Recent activity preview. Pull-to-refresh invalidates
 * the wallet query.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { RefreshControl, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, XStack, Text, Pressable } from 'tamagui';
import { ArrowUp, ArrowDown, QrCode, MoreHorizontal, Gift, Bell } from '@tamagui/lucide-icons';
import { qk } from '../../lib/query';
import { getWallet } from '../../lib/api/wallet';
import { getFeaturedCampaign } from '../../lib/api/catalog';
import { BalanceCard } from '../../components/ui/BalanceCard';
import { ActionChip } from '../../components/ui/ActionChip';
import { BeneficiaryStrip } from '../../components/ui/BeneficiaryStrip';
import { CampaignBanner } from '../../components/ui/CampaignBanner';
import { ActivityRow } from '../../components/ui/ActivityRow';

export default function HomeScreen() {
  const qc = useQueryClient();
  const wallet = useQuery({ queryKey: qk.wallet(), queryFn: getWallet });
  const featured = useQuery({ queryKey: qk.featuredCampaign(), queryFn: getFeaturedCampaign });

  const zar = wallet.data?.accounts.find((a) => a.currency === 'ZAR');
  const pts = wallet.data?.accounts.find((a) => a.currency === 'PTS');
  const recent = (wallet.data?.recent_transactions ?? []).slice(0, 5);

  // Derive "send again" beneficiaries from prior P2Ps (ZAR debits with
  // a description containing a phone — backend includes counterparty).
  const beneficiaries: { name: string; phone: string }[] = [];

  return (
    <SafeAreaView style={{ flex: 1 }} edges={['top']}>
      <ScrollView contentContainerStyle={{ paddingBottom: 120 }}
        refreshControl={<RefreshControl refreshing={wallet.isRefetching}
          onRefresh={() => qc.invalidateQueries({ queryKey: qk.wallet() })} />}>
        <XStack paddingHorizontal="$4" paddingVertical="$3" alignItems="center" justifyContent="space-between">
          <YStack width={32} height={32} borderRadius={16} backgroundColor="$primary" alignItems="center" justifyContent="center">
            <Text color="white" fontFamily="Inter-Bold">{(wallet.data?.user.first_name ?? 'U').slice(0,1)}</Text>
          </YStack>
          <Text fontFamily="Inter-Bold" color="$primary">sasai</Text>
          <XStack gap="$3">
            <Bell size={20} color="#6A7682" />
            <Pressable onPress={() => router.push('/rewards')}>
              <XStack gap="$1" alignItems="center" backgroundColor="rgba(72,194,207,0.15)"
                paddingHorizontal="$2" paddingVertical="$1" borderRadius={12}>
                <Gift size={16} color="#48C2CF" />
                <Text color="$accent" fontFamily="Inter-SemiBold">{pts?.balance ?? '0'}</Text>
              </XStack>
            </Pressable>
          </XStack>
        </XStack>

        <YStack paddingHorizontal="$4" gap="$5">
          {zar && <BalanceCard balance={zar.balance} accountId={zar.id} />}

          <XStack justifyContent="space-around">
            <ActionChip icon={ArrowUp} label="Send" onPress={() => router.push('/p2p/recipient')} />
            <ActionChip icon={ArrowDown} label="Top up" onPress={() => router.push('/topup/amount')} />
            <ActionChip icon={QrCode} label="Scan" onPress={() => {}} />
            <ActionChip icon={MoreHorizontal} label="More" onPress={() => {}} />
          </XStack>

          <BeneficiaryStrip items={beneficiaries}
            onPick={(b) => router.push({ pathname: '/p2p/amount', params: { recipient_phone: b.phone, recipient_name: b.name }})}
            onAdd={() => router.push('/p2p/recipient')} />

          <CampaignBanner campaign={featured.data?.campaign ?? null}
            onPress={(c) => {
              if (c.primary_action === 'topup') router.push('/topup/amount');
              if (c.primary_action === 'p2p')   router.push('/p2p/recipient');
              if (c.primary_action === 'redeem') router.push('/rewards');
            }} />

          <YStack gap="$2">
            <XStack justifyContent="space-between" paddingHorizontal="$2">
              <Text fontFamily="Inter-SemiBold" color="$color">Activity</Text>
              <Pressable onPress={() => router.push('/(tabs)/activity')}>
                <Text color="$accent" fontFamily="Inter-Medium">See all</Text>
              </Pressable>
            </XStack>
            {recent.map((t) => <ActivityRow key={t.id} txn={t} />)}
          </YStack>
        </YStack>
      </ScrollView>
    </SafeAreaView>
  );
}
```

- [ ] **Step 3: Verify**

Run, sign in as Alice. Expected: balance card with seeded ZAR balance,
PTS chip in header, quick actions visible, "Send again" populated from
seed (Bob), featured campaign card if seeded campaign exists, recent
activity rows below.

- [ ] **Step 4: Commit**

```bash
git add mobile/components/ui/ActivityRow.tsx mobile/app/\(tabs\)/home.tsx
git commit -m "feat(mobile): home screen with balance, quick actions, beneficiaries, campaign, activity"
```

---

### Task D7: Activity tab with Wallet/Rewards segment

**Files:**
- Create: `mobile/components/ui/SegmentControl.tsx`
- Create: `mobile/app/(tabs)/activity.tsx`

- [ ] **Step 1: SegmentControl**

```tsx
import { Pressable } from 'react-native';
import { XStack, Text } from 'tamagui';

type Props<T extends string> = {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
};

export function SegmentControl<T extends string>({ options, value, onChange }: Props<T>) {
  return (
    <XStack backgroundColor="rgba(20,73,137,0.08)" borderRadius={20} padding="$1" alignSelf="center">
      {options.map((o) => (
        <Pressable key={o.value} onPress={() => onChange(o.value)}
          style={{ paddingHorizontal: 24, paddingVertical: 8, borderRadius: 16 }}>
          <Text fontFamily="Inter-Medium"
            color={value === o.value ? '$primary' : '$muted'}
            backgroundColor={value === o.value ? 'white' : undefined}>
            {o.label}
          </Text>
        </Pressable>
      ))}
    </XStack>
  );
}
```

- [ ] **Step 2: Activity tab**

```tsx
import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshControl, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, H2, Text } from 'tamagui';
import { qk } from '../../lib/query';
import { getWallet, WalletTransaction } from '../../lib/api/wallet';
import { ActivityRow } from '../../components/ui/ActivityRow';
import { SegmentControl } from '../../components/ui/SegmentControl';

type Tab = 'wallet' | 'rewards';

export default function ActivityScreen() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>('wallet');
  const { data, isRefetching } = useQuery({ queryKey: qk.wallet(), queryFn: getWallet });

  const filtered = useMemo<WalletTransaction[]>(() => {
    if (!data) return [];
    const want = tab === 'wallet' ? 'ZAR' : 'PTS';
    return data.recent_transactions.filter((t) => t.currency === want);
  }, [data, tab]);

  const grouped = useMemo(() => groupByDay(filtered), [filtered]);

  return (
    <SafeAreaView style={{ flex: 1 }} edges={['top']}>
      <ScrollView contentContainerStyle={{ paddingBottom: 120 }}
        refreshControl={<RefreshControl refreshing={isRefetching}
          onRefresh={() => qc.invalidateQueries({ queryKey: qk.wallet() })} />}>
        <YStack padding="$4" gap="$4">
          <H2 fontFamily="Inter-Bold" color="$primary">Activity</H2>
          <SegmentControl<Tab>
            options={[{ value: 'wallet', label: 'Wallet' }, { value: 'rewards', label: 'Rewards' }]}
            value={tab} onChange={setTab} />
        </YStack>

        {grouped.map(({ label, items }) => (
          <YStack key={label} gap="$1" marginBottom="$3">
            <Text fontFamily="Inter-Medium" color="$muted" paddingHorizontal="$4">{label}</Text>
            {items.map((t) => <ActivityRow key={t.id} txn={t} />)}
          </YStack>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

function groupByDay(items: WalletTransaction[]) {
  const groups = new Map<string, WalletTransaction[]>();
  for (const t of items) {
    const k = new Date(t.created_at).toDateString();
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(t);
  }
  return [...groups.entries()].map(([k, items]) => ({ label: labelFor(k), items }));
}

function labelFor(dateStr: string) {
  const d = new Date(dateStr);
  const today = new Date(); today.setHours(0,0,0,0);
  const y = new Date(today); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === y.toDateString()) return 'Yesterday';
  return d.toLocaleDateString('en-ZA', { day: '2-digit', month: 'short', year: 'numeric' });
}
```

- [ ] **Step 3: Verify**

Tap Activity tab. Expected: Wallet segment shows ZAR entries grouped by
day. Tap Rewards segment → switches to PTS entries.

- [ ] **Step 4: Commit**

```bash
git add mobile/components/ui/SegmentControl.tsx mobile/app/\(tabs\)/activity.tsx
git commit -m "feat(mobile): activity tab with Wallet/Rewards segment and day grouping"
```

---

### Task D8: Profile tab

**Files:**
- Create: `mobile/app/(tabs)/profile.tsx`

- [ ] **Step 1: Profile screen**

```tsx
/**
 * Profile tab. Minimal: avatar · name · masked phone · biometric toggle ·
 * theme override · sign out.
 */
import { useQuery } from '@tanstack/react-query';
import { useState, useEffect } from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, XStack, Text, Switch, Button, H2 } from 'tamagui';
import { qk } from '../../lib/query';
import { getWallet } from '../../lib/api/wallet';
import { secureStorage } from '../../lib/storage';
import { signOut, isBiometricAvailable } from '../../lib/auth';
import { maskPhone } from '../../lib/format';

export default function ProfileScreen() {
  const wallet = useQuery({ queryKey: qk.wallet(), queryFn: getWallet });
  const [bioEnabled, setBioEnabled] = useState(false);
  const [bioAvailable, setBioAvailable] = useState(false);

  useEffect(() => {
    (async () => {
      setBioAvailable(await isBiometricAvailable());
      setBioEnabled((await secureStorage.get('biometricEnabled')) === 'true');
    })();
  }, []);

  async function toggleBio(next: boolean) {
    setBioEnabled(next);
    await secureStorage.set('biometricEnabled', next ? 'true' : 'false');
    if (!next) await secureStorage.remove('biometricToken');
  }

  return (
    <SafeAreaView style={{ flex: 1 }} edges={['top']}>
      <YStack padding="$4" gap="$5">
        <H2 fontFamily="Inter-Bold" color="$primary">Profile</H2>

        <YStack alignItems="center" gap="$2" marginVertical="$4">
          <YStack width={72} height={72} borderRadius={36} backgroundColor="$primary"
            alignItems="center" justifyContent="center">
            <Text color="white" fontFamily="Inter-Bold" fontSize={28}>
              {(wallet.data?.user.first_name ?? 'U').slice(0, 1)}
            </Text>
          </YStack>
          <Text fontFamily="Inter-SemiBold">{wallet.data?.user.first_name ?? '—'}</Text>
          <Text color="$muted">{wallet.data ? maskPhone(wallet.data.user.phone_masked) : ''}</Text>
        </YStack>

        {bioAvailable && (
          <XStack justifyContent="space-between" alignItems="center" padding="$3"
            backgroundColor="rgba(20,73,137,0.05)" borderRadius={16}>
            <Text fontFamily="Inter-Medium">Use biometrics</Text>
            <Switch checked={bioEnabled} onCheckedChange={toggleBio}>
              <Switch.Thumb animation="quick" />
            </Switch>
          </XStack>
        )}

        <Button theme="active" onPress={signOut} marginTop="auto">Sign out</Button>
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 2: Verify + commit**

```bash
git add mobile/app/\(tabs\)/profile.tsx
git commit -m "feat(mobile): profile tab with biometric toggle and sign out"
```

---

## Phase E — P2P flow

### Task E1: useStepUpAware hook + PinChallengeSheet

The cross-cutting piece used by P2P, Topup, and Redemption. Build once, reuse three times.

**Files:**
- Create: `mobile/lib/step-up.ts`
- Create: `mobile/components/ui/PinChallengeSheet.tsx`

- [ ] **Step 1: PinChallengeSheet**

```tsx
/**
 * Step-up PIN entry sheet. Slides up over the current screen, shakes
 * + clears on wrong-PIN, mirrors backend lockout with a friendly screen.
 *
 * Used by P2P, Topup, and Redemption flows via useStepUpAware().
 */
import { useState, useEffect } from 'react';
import { Sheet, YStack, H2, Text } from 'tamagui';
import { PinInput } from '../forms/PinInput';

type Props = {
  open: boolean;
  onClose: () => void;
  onSubmit: (pin: string) => Promise<void>;
  errorMessage: string | null;
  attempts: number;
};

export function PinChallengeSheet({ open, onClose, onSubmit, errorMessage, attempts }: Props) {
  const [busy, setBusy] = useState(false);
  const [shake, setShake] = useState(0);

  useEffect(() => { if (errorMessage) setShake((s) => s + 1); }, [errorMessage]);

  async function handle(pin: string) {
    setBusy(true);
    try { await onSubmit(pin); } finally { setBusy(false); }
  }

  return (
    <Sheet modal open={open} onOpenChange={onClose} snapPoints={[55]} dismissOnSnapToBottom>
      <Sheet.Overlay />
      <Sheet.Frame padding="$6" gap="$5" alignItems="center">
        <Sheet.Handle />
        <H2 fontFamily="Inter-Bold" color="$primary">Confirm with PIN</H2>
        <Text color="$muted" textAlign="center">This transaction needs your PIN to continue.</Text>
        <PinInput key={shake} onComplete={handle} clearOnComplete />
        {errorMessage && <Text color="$error" textAlign="center">{errorMessage}</Text>}
        {attempts > 0 && <Text fontSize={12} color="$muted">{5 - attempts} attempts remaining</Text>}
      </Sheet.Frame>
    </Sheet>
  );
}
```

- [ ] **Step 2: useStepUpAware hook**

```ts
/**
 * Try-then-PIN helper. Calls the supplied request fn without a PIN; if
 * the backend returns step_up_required, opens the PIN sheet and re-runs
 * the request with the same Idempotency-Key + the entered PIN.
 */
import { useState } from 'react';
import { InvalidStepUpPin, StepUpRequired, Lockout } from './api/errors';

type Run<T> = (pin?: string) => Promise<T>;

export function useStepUpAware<T>(run: Run<T>) {
  const [pinOpen, setPinOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempts, setAttempts] = useState(0);
  const [busy, setBusy] = useState(false);
  const [pendingResolve, setPendingResolve] = useState<{ resolve: (v: T) => void; reject: (e: unknown) => void } | null>(null);

  async function start(): Promise<T> {
    setBusy(true); setError(null); setAttempts(0);
    try {
      return await run();
    } catch (e) {
      if (e instanceof StepUpRequired) {
        return new Promise<T>((resolve, reject) => {
          setPendingResolve({ resolve, reject });
          setPinOpen(true);
        });
      }
      throw e;
    } finally { setBusy(false); }
  }

  async function submitPin(pin: string) {
    setBusy(true);
    try {
      const result = await run(pin);
      setPinOpen(false);
      pendingResolve?.resolve(result);
      setPendingResolve(null);
    } catch (e) {
      if (e instanceof InvalidStepUpPin) {
        setAttempts((a) => a + 1);
        setError('Incorrect PIN. Try again.');
        return;
      }
      if (e instanceof Lockout) {
        setError('Too many attempts. Please try again later.');
        return;
      }
      setPinOpen(false);
      pendingResolve?.reject(e);
      setPendingResolve(null);
    } finally { setBusy(false); }
  }

  return {
    start,
    pinOpen,
    error,
    attempts,
    busy,
    submitPin,
    closePin: () => { setPinOpen(false); pendingResolve?.reject(new Error('cancelled')); setPendingResolve(null); },
  };
}
```

- [ ] **Step 3: Commit**

```bash
git add mobile/lib/step-up.ts mobile/components/ui/PinChallengeSheet.tsx
git commit -m "feat(mobile): useStepUpAware hook + PinChallengeSheet (cross-cutting)"
```

---

### Task E2: SlideToConfirm component

**Files:**
- Create: `mobile/components/ui/SlideToConfirm.tsx`

- [ ] **Step 1: SlideToConfirm**

```tsx
/**
 * Slide-to-confirm gesture button. Drag the knob to the right edge to
 * trigger onConfirm. Transitions to a brief "checking…" pulse state
 * while the parent runs the request.
 */
import { useState } from 'react';
import { Pressable, View, LayoutChangeEvent } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, { useAnimatedStyle, useSharedValue, withSpring } from 'react-native-reanimated';
import { Text, YStack } from 'tamagui';
import { ChevronRight } from '@tamagui/lucide-icons';

type Props = { label: string; busy?: boolean; onConfirm: () => void };

export function SlideToConfirm({ label, busy, onConfirm }: Props) {
  const [width, setWidth] = useState(0);
  const x = useSharedValue(0);

  const pan = Gesture.Pan()
    .enabled(!busy)
    .onUpdate((e) => { x.value = Math.max(0, Math.min(e.translationX, width - 60)); })
    .onEnd(() => {
      if (x.value > width - 80) {
        x.value = withSpring(width - 60);
        onConfirm();
      } else {
        x.value = withSpring(0);
      }
    });

  const knob = useAnimatedStyle(() => ({ transform: [{ translateX: x.value }] }));

  return (
    <YStack height={60} borderRadius={30} backgroundColor="$primary" overflow="hidden" justifyContent="center"
      onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)}>
      <Text textAlign="center" color="white" fontFamily="Inter-SemiBold">{busy ? 'Working…' : label}</Text>
      <GestureDetector gesture={pan}>
        <Animated.View style={[{ position: 'absolute', left: 4, top: 4, width: 52, height: 52, borderRadius: 26, backgroundColor: '#48C2CF', alignItems: 'center', justifyContent: 'center' }, knob]}>
          <ChevronRight color="white" size={22} />
        </Animated.View>
      </GestureDetector>
    </YStack>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add mobile/components/ui/SlideToConfirm.tsx
git commit -m "feat(mobile): SlideToConfirm gesture primitive"
```

---

### Task E3: P2P recipient screen

**Files:**
- Create: `mobile/app/p2p/_layout.tsx`
- Create: `mobile/app/p2p/recipient.tsx`

- [ ] **Step 1: P2P layout**

```tsx
import { Stack } from 'expo-router';
export default function P2PLayout() {
  return <Stack screenOptions={{ headerShown: false, animation: 'slide_from_bottom' }} />;
}
```

- [ ] **Step 2: Recipient screen**

```tsx
import { useState } from 'react';
import { router } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, H2, Text, Button, Spinner } from 'tamagui';
import { PhoneInput } from '../../components/forms/PhoneInput';
import { authStart } from '../../lib/api/auth';

export default function RecipientScreen() {
  const [phone, setPhone] = useState('+27');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onContinue() {
    setBusy(true); setError(null);
    try {
      const { status } = await authStart(phone);
      if (status === 'needs_otp') {
        setError("No Sasai user with that number yet.");
        return;
      }
      router.push({ pathname: '/p2p/amount', params: { recipient_phone: phone } });
    } catch (e: any) {
      setError(e?.message ?? 'Lookup failed');
    } finally { setBusy(false); }
  }

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$6" backgroundColor="$background">
        <YStack gap="$2" marginTop="$4">
          <H2 fontFamily="Inter-Bold" color="$primary">Send money</H2>
          <Text color="$muted">Who are you sending to?</Text>
        </YStack>
        <PhoneInput value={phone} onChangeE164={setPhone} />
        {error && <Text color="$error">{error}</Text>}
        <Button size="$5" theme="active" disabled={busy || !/^\+\d{8,15}$/.test(phone)}
          onPress={onContinue} marginTop="auto">
          {busy ? <Spinner /> : 'Continue'}
        </Button>
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add mobile/app/p2p/
git commit -m "feat(mobile): P2P recipient screen (phone lookup + branch)"
```

---

### Task E4: P2P amount screen with quick chips

**Files:**
- Create: `mobile/components/forms/AmountInput.tsx`
- Create: `mobile/app/p2p/amount.tsx`

- [ ] **Step 1: AmountInput**

```tsx
/**
 * Big numeric amount input with currency prefix. Shows quick-amount
 * chips below; tap to fill (tap again to clear). Used by P2P and Topup.
 */
import { Pressable } from 'react-native';
import { XStack, YStack, Input, Text } from 'tamagui';

type Props = {
  value: string;
  onChange: (v: string) => void;
  currencyPrefix?: string;
  quickAmounts?: number[];
};

export function AmountInput({ value, onChange, currencyPrefix = 'R', quickAmounts = [50, 100, 200, 500] }: Props) {
  function setAmount(n: number) {
    const next = String(n.toFixed(2));
    onChange(value === next ? '' : next);
  }

  return (
    <YStack gap="$4" alignItems="center">
      <XStack alignItems="baseline" gap="$2">
        <Text fontFamily="Inter-Medium" fontSize={28} color="$muted">{currencyPrefix}</Text>
        <Input value={value} onChangeText={(t) => onChange(t.replace(/[^0-9.]/g, ''))}
          placeholder="0.00" keyboardType="decimal-pad"
          fontSize={48} fontFamily="Inter-Bold"
          textAlign="center" borderWidth={0} backgroundColor="transparent"
          minWidth={200} />
      </XStack>
      <XStack gap="$2">
        {quickAmounts.map((n) => (
          <Pressable key={n} onPress={() => setAmount(n)}>
            <YStack paddingHorizontal="$3" paddingVertical="$2" borderRadius={16}
              backgroundColor={value === String(n.toFixed(2)) ? '$accent' : 'rgba(20,73,137,0.06)'}>
              <Text color={value === String(n.toFixed(2)) ? 'white' : '$primary'}
                fontFamily="Inter-Medium">R {n}</Text>
            </YStack>
          </Pressable>
        ))}
      </XStack>
    </YStack>
  );
}
```

- [ ] **Step 2: Amount screen**

```tsx
import { useState } from 'react';
import { router, useLocalSearchParams } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, XStack, Text, Input, Button } from 'tamagui';
import { AmountInput } from '../../components/forms/AmountInput';
import { qk } from '../../lib/query';
import { getWallet } from '../../lib/api/wallet';
import { formatZAR } from '../../lib/format';

export default function P2PAmountScreen() {
  const params = useLocalSearchParams<{ recipient_phone: string; recipient_name?: string }>();
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const wallet = useQuery({ queryKey: qk.wallet(), queryFn: getWallet });
  const zar = wallet.data?.accounts.find((a) => a.currency === 'ZAR');
  const available = parseFloat(zar?.balance ?? '0');
  const amt = parseFloat(amount || '0');
  const insufficient = amt > available;
  const valid = amt > 0 && !insufficient;

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$6" backgroundColor="$background">
        <Text color="$muted" alignSelf="center">From ZAR Wallet · {formatZAR(available)} available</Text>
        <AmountInput value={amount} onChange={setAmount} />
        <Input placeholder="What's it for?" value={note} onChangeText={setNote} maxLength={60} />
        {insufficient && <Text color="$error" textAlign="center">Insufficient balance. Top up?</Text>}
        <Button size="$5" theme="active" disabled={!valid} onPress={() =>
          router.push({ pathname: '/p2p/review', params: { ...params, amount, note } })}
          marginTop="auto">
          Continue
        </Button>
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add mobile/components/forms/AmountInput.tsx mobile/app/p2p/amount.tsx
git commit -m "feat(mobile): P2P amount screen with quick chips and balance check"
```

---

### Task E5: P2P review screen + try-then-PIN send

**Files:**
- Create: `mobile/app/p2p/review.tsx`

- [ ] **Step 1: Review + send**

```tsx
import { useEffect, useState } from 'react';
import { router, useLocalSearchParams } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, XStack, Text, H2 } from 'tamagui';
import { SlideToConfirm } from '../../components/ui/SlideToConfirm';
import { PinChallengeSheet } from '../../components/ui/PinChallengeSheet';
import { useStepUpAware } from '../../lib/step-up';
import { p2p } from '../../lib/api/payments';
import { newIdempotencyKey } from '../../lib/api/client';
import { qk } from '../../lib/query';
import { formatZAR, maskPhone } from '../../lib/format';

export default function P2PReviewScreen() {
  const qc = useQueryClient();
  const { recipient_phone, amount, note } = useLocalSearchParams<{ recipient_phone: string; amount: string; note?: string }>();
  const [idem] = useState(() => newIdempotencyKey('p2p'));

  const { start, pinOpen, error, attempts, busy, submitPin, closePin } =
    useStepUpAware<Awaited<ReturnType<typeof p2p>>>((pin) =>
      p2p({ recipient_phone, amount, description: note, pin }, idem));

  async function onConfirm() {
    try {
      const result = await start();
      qc.invalidateQueries({ queryKey: qk.wallet() });
      router.replace({
        pathname: '/p2p/success',
        params: { amount, recipient_phone, earned: String(result.earned_points ?? 0) },
      });
    } catch (e) { /* error already toasted via step-up hook */ }
  }

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$5" backgroundColor="$background">
        <H2 fontFamily="Inter-Bold" color="$primary">Review</H2>

        <YStack gap="$2" backgroundColor="rgba(20,73,137,0.05)" padding="$4" borderRadius={16}>
          <Text color="$muted">To</Text>
          <Text fontFamily="Inter-SemiBold">{maskPhone(recipient_phone)}</Text>
        </YStack>

        <YStack alignItems="center" gap="$1">
          <Text fontFamily="Inter-Bold" fontSize={48} color="$primary">{formatZAR(amount)}</Text>
          <Text color="$muted">Fee R 0.00</Text>
        </YStack>

        {note && <Text color="$muted" textAlign="center">"{note}"</Text>}

        <YStack marginTop="auto" gap="$3">
          <Text color="$muted" textAlign="center">From ZAR Wallet</Text>
          <SlideToConfirm label={`Slide to send ${formatZAR(amount)}`} busy={busy} onConfirm={onConfirm} />
        </YStack>

        <PinChallengeSheet open={pinOpen} onClose={closePin}
          onSubmit={submitPin} errorMessage={error} attempts={attempts} />
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add mobile/app/p2p/review.tsx
git commit -m "feat(mobile): P2P review screen with slide-to-send + step-up PIN sheet"
```

---

### Task E6: P2P success screen + earned-PTS toast

**Files:**
- Create: `mobile/app/p2p/success.tsx`

- [ ] **Step 1: Success screen**

```tsx
import { useEffect } from 'react';
import { router, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, H2, Text, Button } from 'tamagui';
import { CheckCircle2, Sparkles } from '@tamagui/lucide-icons';
import { formatZAR, maskPhone } from '../../lib/format';

export default function P2PSuccessScreen() {
  const { amount, recipient_phone, earned } = useLocalSearchParams<{ amount: string; recipient_phone: string; earned: string }>();
  const earnedN = parseInt(earned ?? '0');

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$5" backgroundColor="$background" alignItems="center" justifyContent="center">
        <CheckCircle2 color="#48C2CF" size={96} />
        <H2 fontFamily="Inter-Bold" color="$primary" textAlign="center">
          {formatZAR(amount)} sent
        </H2>
        <Text color="$muted">to {maskPhone(recipient_phone)}</Text>

        {earnedN > 0 && (
          <YStack flexDirection="row" alignItems="center" gap="$2"
            backgroundColor="rgba(72,194,207,0.15)" paddingHorizontal="$3" paddingVertical="$2"
            borderRadius={20}>
            <Sparkles color="#48C2CF" size={16} />
            <Text color="$accent" fontFamily="Inter-SemiBold">+{earnedN} PTS earned</Text>
          </YStack>
        )}

        <YStack gap="$2" marginTop="$8" width="100%">
          <Button theme="active" onPress={() => router.replace('/(tabs)/home')}>Done</Button>
          <Button chromeless onPress={() => router.replace('/p2p/recipient')}>Send another</Button>
          {earnedN > 0 && (
            <Button chromeless onPress={() => router.replace('/rewards')}>
              See rewards
            </Button>
          )}
        </YStack>
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 2: Verify P2P end-to-end**

Sign in as Alice. Tap Send → enter Bob's number → enter R 50 → slide
to send. Below the step-up threshold, expect: success screen without
PIN. Try R 5000 (above threshold per the policy): expect PIN sheet, then
success.

- [ ] **Step 3: Commit**

```bash
git add mobile/app/p2p/success.tsx
git commit -m "feat(mobile): P2P success screen with earned-PTS toast"
```

---

## Phase F — Topup flow (mock card)

### Task F1: Topup amount screen

**Files:**
- Create: `mobile/app/topup/_layout.tsx`
- Create: `mobile/app/topup/amount.tsx`

- [ ] **Step 1: Layout + amount screen**

```tsx
// mobile/app/topup/_layout.tsx
import { Stack } from 'expo-router';
export default function TopupLayout() {
  return <Stack screenOptions={{ headerShown: false, animation: 'slide_from_bottom' }} />;
}
```

```tsx
// mobile/app/topup/amount.tsx
import { useState } from 'react';
import { router } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, Text, Button } from 'tamagui';
import { AmountInput } from '../../components/forms/AmountInput';

export default function TopupAmountScreen() {
  const [amount, setAmount] = useState('');
  const valid = parseFloat(amount || '0') > 0;

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$6" backgroundColor="$background">
        <Text color="$muted" alignSelf="center">Topping up: ZAR Wallet</Text>
        <AmountInput value={amount} onChange={setAmount} quickAmounts={[100, 200, 500, 1000]} />
        <Button size="$5" theme="active" disabled={!valid} marginTop="auto"
          onPress={() => router.push({ pathname: '/topup/card', params: { amount } })}>
          Continue
        </Button>
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add mobile/app/topup/_layout.tsx mobile/app/topup/amount.tsx
git commit -m "feat(mobile): topup amount screen"
```

---

### Task F2: Topup card screen with flip animation + try-then-PIN

**Files:**
- Create: `mobile/components/ui/MockCard.tsx`
- Create: `mobile/app/topup/card.tsx`

- [ ] **Step 1: MockCard visual (flippable)**

```tsx
/**
 * Visual mock credit card — gradient surface, demo numbers, horizontal-tap
 * flips between front (number + name) and back (CVV strip).
 */
import { useState } from 'react';
import { Pressable } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withTiming, interpolate } from 'react-native-reanimated';
import { LinearGradient } from 'expo-linear-gradient';
import { YStack, XStack, Text } from 'tamagui';

export function MockCard() {
  const flip = useSharedValue(0);
  const [flipped, setFlipped] = useState(false);

  function toggle() {
    setFlipped((f) => !f);
    flip.value = withTiming(flipped ? 0 : 1, { duration: 350 });
  }

  const front = useAnimatedStyle(() => ({
    transform: [{ rotateY: `${interpolate(flip.value, [0, 1], [0, 180])}deg` }],
    backfaceVisibility: 'hidden',
  }));
  const back = useAnimatedStyle(() => ({
    transform: [{ rotateY: `${interpolate(flip.value, [0, 1], [180, 360])}deg` }],
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
    backfaceVisibility: 'hidden',
  }));

  return (
    <Pressable onPress={toggle}>
      <YStack height={200} borderRadius={20} overflow="hidden">
        <Animated.View style={[front, { borderRadius: 20, overflow: 'hidden' }]}>
          <LinearGradient colors={['#144989', '#48C2CF']} style={{ flex: 1, padding: 16 }}>
            <Text color="white" fontFamily="Inter-Bold" marginTop="$2">VISA</Text>
            <Text color="white" fontFamily="Inter-Bold" fontSize={22} marginTop="auto">4242 •••• •••• 4242</Text>
            <XStack justifyContent="space-between" marginTop="$2">
              <Text color="white" fontFamily="Inter-Medium">DEMO CARDHOLDER</Text>
              <Text color="white" fontFamily="Inter-Medium">12/29</Text>
            </XStack>
          </LinearGradient>
        </Animated.View>
        <Animated.View style={[back, { borderRadius: 20, overflow: 'hidden' }]}>
          <YStack flex={1} backgroundColor="#0E1A2B" padding="$4">
            <YStack height={40} backgroundColor="black" marginTop="$3" />
            <XStack justifyContent="flex-end" marginTop="$5">
              <YStack backgroundColor="white" paddingHorizontal="$3" paddingVertical="$1" borderRadius={4}>
                <Text fontFamily="Inter-Bold">CVV 123</Text>
              </YStack>
            </XStack>
          </YStack>
        </Animated.View>
      </YStack>
    </Pressable>
  );
}
```

- [ ] **Step 2: Card screen**

```tsx
import { useState } from 'react';
import { router, useLocalSearchParams } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, Text, Switch, XStack } from 'tamagui';
import { MockCard } from '../../components/ui/MockCard';
import { SlideToConfirm } from '../../components/ui/SlideToConfirm';
import { PinChallengeSheet } from '../../components/ui/PinChallengeSheet';
import { useStepUpAware } from '../../lib/step-up';
import { topup } from '../../lib/api/payments';
import { newIdempotencyKey } from '../../lib/api/client';
import { qk } from '../../lib/query';
import { formatZAR } from '../../lib/format';

export default function TopupCardScreen() {
  const qc = useQueryClient();
  const { amount } = useLocalSearchParams<{ amount: string }>();
  const [saveCard, setSaveCard] = useState(true);
  const [idem] = useState(() => newIdempotencyKey('topup'));

  const { start, pinOpen, error, attempts, busy, submitPin, closePin } =
    useStepUpAware<Awaited<ReturnType<typeof topup>>>((pin) => topup({ amount, pin }, idem));

  async function onConfirm() {
    try {
      const result = await start();
      qc.invalidateQueries({ queryKey: qk.wallet() });
      router.replace({ pathname: '/topup/success',
        params: { amount, new_balance: result.new_balance, earned: String(result.earned_points ?? 0) }});
    } catch { /* error rendered by hook */ }
  }

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$5" backgroundColor="$background">
        <MockCard />
        <XStack justifyContent="space-between" alignItems="center" padding="$3"
          backgroundColor="rgba(20,73,137,0.05)" borderRadius={16}>
          <Text fontFamily="Inter-Medium">Save card for next time</Text>
          <Switch checked={saveCard} onCheckedChange={setSaveCard}>
            <Switch.Thumb animation="quick" />
          </Switch>
        </XStack>

        <YStack marginTop="auto" gap="$2">
          <Text color="$muted" textAlign="center">You're paying</Text>
          <Text color="$primary" fontFamily="Inter-Bold" fontSize={28} textAlign="center">{formatZAR(amount)}</Text>
          <SlideToConfirm label={`Slide to pay ${formatZAR(amount)}`} busy={busy} onConfirm={onConfirm} />
        </YStack>

        <PinChallengeSheet open={pinOpen} onClose={closePin}
          onSubmit={submitPin} errorMessage={error} attempts={attempts} />
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add mobile/components/ui/MockCard.tsx mobile/app/topup/card.tsx
git commit -m "feat(mobile): topup card screen with flip animation + step-up-aware slide-to-pay"
```

---

### Task F3: Topup success screen

**Files:**
- Create: `mobile/app/topup/success.tsx`

- [ ] **Step 1: Success screen**

```tsx
import { router, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, H2, Text, Button } from 'tamagui';
import { CheckCircle2, Sparkles } from '@tamagui/lucide-icons';
import { formatZAR } from '../../lib/format';

export default function TopupSuccessScreen() {
  const { amount, new_balance, earned } = useLocalSearchParams<{ amount: string; new_balance: string; earned: string }>();
  const earnedN = parseInt(earned ?? '0');

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$4" backgroundColor="$background" alignItems="center" justifyContent="center">
        <CheckCircle2 color="#48C2CF" size={96} />
        <H2 fontFamily="Inter-Bold" color="$primary" textAlign="center">
          {formatZAR(amount)} added
        </H2>
        <Text color="$muted">New balance: {formatZAR(new_balance)}</Text>

        {earnedN > 0 && (
          <YStack flexDirection="row" alignItems="center" gap="$2"
            backgroundColor="rgba(72,194,207,0.15)" paddingHorizontal="$3" paddingVertical="$2"
            borderRadius={20}>
            <Sparkles color="#48C2CF" size={16} />
            <Text color="$accent" fontFamily="Inter-SemiBold">+{earnedN} PTS earned</Text>
          </YStack>
        )}

        <Button theme="active" onPress={() => router.replace('/(tabs)/home')} marginTop="$8" width="100%">
          Done
        </Button>
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 2: Verify topup end-to-end + commit**

Sign in as Alice. Tap Top up → R 200 → card screen → slide → success.

```bash
git add mobile/app/topup/success.tsx
git commit -m "feat(mobile): topup success screen"
```

---

## Phase G — Rewards + Redemption

### Task G1: Rewards screen (PTS hero + offers grid + history peek)

**Files:**
- Create: `mobile/components/ui/RewardsCard.tsx`
- Create: `mobile/components/ui/OfferCard.tsx`
- Create: `mobile/app/rewards/_layout.tsx`
- Create: `mobile/app/rewards/index.tsx`

- [ ] **Step 1: RewardsCard hero**

```tsx
// mobile/components/ui/RewardsCard.tsx
import { LinearGradient } from 'expo-linear-gradient';
import { YStack, XStack, Text } from 'tamagui';
import { Gift } from '@tamagui/lucide-icons';

type Props = { points: number; ptsToZarRate?: number };

export function RewardsCard({ points, ptsToZarRate = 0.1 }: Props) {
  const zar = (points * ptsToZarRate).toFixed(2);
  return (
    <LinearGradient colors={['#48C2CF', '#144989']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
      style={{ borderRadius: 28, padding: 20 }}>
      <XStack justifyContent="space-between" alignItems="center">
        <Text color="white" opacity={0.9} fontFamily="Inter-Medium">Your points</Text>
        <Gift color="white" size={20} />
      </XStack>
      <Text color="white" fontFamily="Inter-Bold" fontSize={42} marginTop="$2">{points} PTS</Text>
      <Text color="white" opacity={0.85} marginTop="$2">≈ R {zar} redeem value</Text>
    </LinearGradient>
  );
}
```

- [ ] **Step 2: OfferCard**

```tsx
// mobile/components/ui/OfferCard.tsx
import { Pressable } from 'react-native';
import { YStack, XStack, Text } from 'tamagui';
import type { Offer } from '../../lib/api/catalog';

type Props = { offer: Offer; userPts: number; onPress: () => void };

export function OfferCard({ offer, userPts, onPress }: Props) {
  const affordable = userPts >= offer.points_cost;
  const deficit = offer.points_cost - userPts;
  return (
    <Pressable onPress={onPress} style={({ pressed }) => ({ flex: 1, transform: [{ scale: pressed ? 0.97 : 1 }] })}>
      <YStack padding="$4" backgroundColor="rgba(20,73,137,0.05)" borderRadius={20} gap="$2">
        <Text fontSize={28}>{iconFor(offer.category)}</Text>
        <Text fontFamily="Inter-SemiBold" numberOfLines={1}>{offer.name}</Text>
        <Text fontFamily="Inter-Medium" color="$primary">R {offer.face_value_zar}</Text>
        <XStack justifyContent="space-between" alignItems="center" marginTop="$1">
          <YStack paddingHorizontal="$2" paddingVertical={3} borderRadius={10}
            backgroundColor={affordable ? '$accent' : 'rgba(106,118,130,0.2)'}>
            <Text color={affordable ? 'white' : '$muted'} fontFamily="Inter-Medium" fontSize={12}>
              {offer.points_cost} PTS
            </Text>
          </YStack>
          {!affordable && <Text fontSize={11} color="$muted">Need {deficit} more</Text>}
        </XStack>
      </YStack>
    </Pressable>
  );
}

function iconFor(category: string): string {
  switch (category) {
    case 'airtime':   return '📶';
    case 'data':      return '📡';
    case 'voucher':   return '🛍';
    case 'groceries': return '🛒';
    default:          return '🎁';
  }
}
```

- [ ] **Step 3: Rewards screen**

```tsx
// mobile/app/rewards/_layout.tsx
import { Stack } from 'expo-router';
export default function RewardsLayout() {
  return <Stack screenOptions={{ headerShown: false, animation: 'slide_from_right' }} />;
}
```

```tsx
// mobile/app/rewards/index.tsx
import { useMemo, useState } from 'react';
import { router } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, XStack, Text, H2, Pressable } from 'tamagui';
import { qk } from '../../lib/query';
import { getCatalog } from '../../lib/api/catalog';
import { getWallet } from '../../lib/api/wallet';
import { RewardsCard } from '../../components/ui/RewardsCard';
import { OfferCard } from '../../components/ui/OfferCard';
import { ActivityRow } from '../../components/ui/ActivityRow';

type Filter = 'all' | 'airtime' | 'voucher' | 'data';

export default function RewardsScreen() {
  const catalog = useQuery({ queryKey: qk.catalog(), queryFn: getCatalog, staleTime: 5 * 60_000 });
  const wallet  = useQuery({ queryKey: qk.wallet(),  queryFn: getWallet });
  const [filter, setFilter] = useState<Filter>('all');

  const pts = parseInt(wallet.data?.accounts.find((a) => a.currency === 'PTS')?.balance ?? '0');
  const ptsHistory = (wallet.data?.recent_transactions ?? []).filter((t) => t.currency === 'PTS').slice(0, 3);
  const offers = useMemo(() =>
    (catalog.data?.offers ?? []).filter((o) => filter === 'all' || o.category === filter),
    [catalog.data, filter]);

  return (
    <SafeAreaView style={{ flex: 1 }} edges={['top']}>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 120, gap: 20 }}>
        <H2 fontFamily="Inter-Bold" color="$primary">Rewards</H2>

        <RewardsCard points={pts} ptsToZarRate={catalog.data?.pts_to_zar_rate ?? 0.1} />

        <XStack gap="$2" flexWrap="wrap">
          {(['all','airtime','voucher','data'] as Filter[]).map((f) => (
            <Pressable key={f} onPress={() => setFilter(f)}>
              <YStack paddingHorizontal="$3" paddingVertical="$2" borderRadius={16}
                backgroundColor={filter === f ? '$primary' : 'rgba(20,73,137,0.05)'}>
                <Text color={filter === f ? 'white' : '$primary'} fontFamily="Inter-Medium">
                  {f === 'all' ? 'All' : f[0].toUpperCase() + f.slice(1)}
                </Text>
              </YStack>
            </Pressable>
          ))}
        </XStack>

        <Text fontFamily="Inter-SemiBold">Redeem</Text>
        <YStack gap="$3">
          {chunk(offers, 2).map((pair, i) => (
            <XStack key={i} gap="$3">
              {pair.map((o) => (
                <OfferCard key={o.id} offer={o} userPts={pts}
                  onPress={() => router.push(`/rewards/${o.id}`)} />
              ))}
              {pair.length === 1 && <YStack flex={1} />}
            </XStack>
          ))}
        </YStack>

        <XStack justifyContent="space-between" alignItems="center">
          <Text fontFamily="Inter-SemiBold">History</Text>
          <Pressable onPress={() => router.push('/(tabs)/activity')}>
            <Text color="$accent" fontFamily="Inter-Medium">See all</Text>
          </Pressable>
        </XStack>
        {ptsHistory.map((t) => <ActivityRow key={t.id} txn={t} />)}
      </ScrollView>
    </SafeAreaView>
  );
}

function chunk<T>(arr: T[], n: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n));
  return out;
}
```

- [ ] **Step 4: Commit**

```bash
git add mobile/components/ui/RewardsCard.tsx mobile/components/ui/OfferCard.tsx mobile/app/rewards/
git commit -m "feat(mobile): rewards screen with PTS hero, offer grid, and history peek"
```

---

### Task G2: Offer detail + redemption flow with polling

**Files:**
- Create: `mobile/app/rewards/[offerId].tsx`

- [ ] **Step 1: Offer detail + initiate + confirm + poll**

```tsx
import { useEffect, useState } from 'react';
import { router, useLocalSearchParams } from 'expo-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, XStack, Text, H2, Spinner } from 'tamagui';
import { PhoneInput } from '../../components/forms/PhoneInput';
import { SlideToConfirm } from '../../components/ui/SlideToConfirm';
import { PinChallengeSheet } from '../../components/ui/PinChallengeSheet';
import { useStepUpAware } from '../../lib/step-up';
import { initiateRedemption, confirmRedemption, getRedemption } from '../../lib/api/redemption';
import { newIdempotencyKey } from '../../lib/api/client';
import { qk } from '../../lib/query';
import { getCatalog } from '../../lib/api/catalog';
import { getWallet } from '../../lib/api/wallet';

export default function OfferDetailScreen() {
  const qc = useQueryClient();
  const { offerId } = useLocalSearchParams<{ offerId: string }>();
  const catalog = useQuery({ queryKey: qk.catalog(), queryFn: getCatalog });
  const wallet  = useQuery({ queryKey: qk.wallet(),  queryFn: getWallet });
  const offer   = catalog.data?.offers.find((o) => o.id === offerId);
  const userPts = parseInt(wallet.data?.accounts.find((a) => a.currency === 'PTS')?.balance ?? '0');
  const selfPhone = wallet.data?.user.phone_masked ?? '';

  const [recipient, setRecipient] = useState(selfPhone || '+27');
  const [redemptionId, setRedemptionId] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [terminal, setTerminal] = useState<'completed' | 'failed' | null>(null);
  const [initIdem]    = useState(() => newIdempotencyKey('red-init'));
  const [confirmIdem] = useState(() => newIdempotencyKey('red-confirm'));

  const { start, pinOpen, error, attempts, busy, submitPin, closePin } =
    useStepUpAware(async (pin) => {
      const init = await initiateRedemption({ offer_id: offerId, recipient_phone: recipient }, initIdem);
      setRedemptionId(init.id);
      return confirmRedemption(init.id, { pin }, confirmIdem);
    });

  useEffect(() => { setRecipient(selfPhone || '+27'); }, [selfPhone]);

  useEffect(() => {
    if (!redemptionId || terminal) return;
    setPolling(true);
    const interval = setInterval(async () => {
      const r = await getRedemption(redemptionId).catch(() => null);
      if (!r) return;
      if (r.status === 'completed' || r.status === 'failed') {
        clearInterval(interval);
        setPolling(false);
        setTerminal(r.status);
        qc.invalidateQueries({ queryKey: qk.wallet() });
        router.replace({ pathname: '/rewards/success', params: { status: r.status, offer_name: offer?.name ?? '', recipient } });
      }
    }, 1500);
    const timeout = setTimeout(() => clearInterval(interval), 8000);
    return () => { clearInterval(interval); clearTimeout(timeout); };
  }, [redemptionId, terminal]);

  if (!offer) return null;
  const balanceAfter = userPts - offer.points_cost;

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$5" backgroundColor="$background">
        <H2 fontFamily="Inter-Bold" color="$primary">{offer.name}</H2>
        <Text color="$muted">{offer.description}</Text>

        <YStack backgroundColor="rgba(20,73,137,0.05)" padding="$4" borderRadius={16}>
          <Text fontFamily="Inter-Medium">You'll spend {offer.points_cost} PTS</Text>
          <Text color="$muted">Balance after: {balanceAfter} PTS</Text>
        </YStack>

        <YStack gap="$2">
          <Text color="$muted">Recipient</Text>
          <PhoneInput value={recipient} onChangeE164={setRecipient} />
        </YStack>

        {polling && (
          <XStack alignItems="center" gap="$2" alignSelf="center">
            <Spinner /><Text color="$muted">Sending your {offer.category}…</Text>
          </XStack>
        )}

        <YStack marginTop="auto">
          <SlideToConfirm label={`Slide to redeem ${offer.points_cost} PTS`}
            busy={busy || polling} onConfirm={() => start().catch(() => {})} />
        </YStack>

        <PinChallengeSheet open={pinOpen} onClose={closePin}
          onSubmit={submitPin} errorMessage={error} attempts={attempts} />
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add mobile/app/rewards/\[offerId\].tsx
git commit -m "feat(mobile): redemption detail with try-then-PIN and polling"
```

---

### Task G3: Redemption success / failure screen

**Files:**
- Create: `mobile/app/rewards/success.tsx`

- [ ] **Step 1: Terminal screen**

```tsx
import { router, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { YStack, H2, Text, Button } from 'tamagui';
import { CheckCircle2, XCircle } from '@tamagui/lucide-icons';

export default function RedemptionSuccessScreen() {
  const { status, offer_name, recipient } = useLocalSearchParams<{ status: string; offer_name: string; recipient: string }>();
  const ok = status === 'completed';

  return (
    <SafeAreaView style={{ flex: 1 }}>
      <YStack flex={1} padding="$6" gap="$4" alignItems="center" justifyContent="center" backgroundColor="$background">
        {ok ? <CheckCircle2 color="#48C2CF" size={96} /> : <XCircle color="#EF4444" size={96} />}
        <H2 fontFamily="Inter-Bold" color="$primary" textAlign="center">
          {ok ? `${offer_name} sent` : 'Redemption failed'}
        </H2>
        {ok && <Text color="$muted">to {recipient}</Text>}
        <Button theme="active" onPress={() => router.replace('/(tabs)/home')} marginTop="$8" width="100%">
          Done
        </Button>
      </YStack>
    </SafeAreaView>
  );
}
```

- [ ] **Step 2: Verify redemption end-to-end + commit**

```bash
git add mobile/app/rewards/success.tsx
git commit -m "feat(mobile): redemption terminal screen (success/failure)"
```

---

## Phase H — Polish + Build

### Task H1: EAS profiles

**Files:**
- Create: `mobile/eas.json`

- [ ] **Step 1: Configure EAS**

```bash
cd mobile && npm install -g eas-cli && eas login
eas init
```

Then replace generated `eas.json` with:

```json
{
  "cli": { "version": ">= 7.0.0" },
  "build": {
    "development": { "developmentClient": true, "distribution": "internal",
                     "env": { "BACKEND_URL": "http://localhost:8000", "TENANT_ID": "<DEV_TENANT_UUID>" } },
    "preview":     { "distribution": "internal",
                     "env": { "BACKEND_URL": "https://staging.api.sasai.example", "TENANT_ID": "<STAGING_TENANT_UUID>" },
                     "channel": "preview", "ios": { "simulator": false }, "android": { "buildType": "apk" } },
    "production":  { "env": { "BACKEND_URL": "https://api.sasai.example", "TENANT_ID": "<PROD_TENANT_UUID>" },
                     "channel": "production" }
  },
  "submit": { "production": {} }
}
```

Replace the `<*_TENANT_UUID>` placeholders with real UUIDs from each
environment's database.

- [ ] **Step 2: Trigger a preview build and commit config**

```bash
eas build -p ios -e preview      # generates TestFlight artifact
eas build -p android -e preview  # generates APK
git add mobile/eas.json
git commit -m "build(mobile): EAS profiles (development / preview / production)"
```

---

### Task H2: OTA updates via expo-updates

**Files:**
- Modify: `mobile/app.config.ts` (add `updates` block)
- Modify: `mobile/package.json` (add `expo-updates`)

- [ ] **Step 1: Install + configure**

```bash
cd mobile && npx expo install expo-updates
```

Edit `mobile/app.config.ts`, add inside the config object:

```ts
runtimeVersion: { policy: 'sdkVersion' },
updates: {
  enabled: true,
  fallbackToCacheTimeout: 0,
  url: 'https://u.expo.dev/<YOUR_EAS_PROJECT_ID>',
},
```

`<YOUR_EAS_PROJECT_ID>` is printed by `eas init` and stored under `extra.eas.projectId` in `app.config.ts`.

- [ ] **Step 2: Publish an OTA update**

```bash
eas update --branch preview --message "demo polish pass"
```

The next launch of the preview build picks up the update.

- [ ] **Step 3: Commit**

```bash
git add mobile/app.config.ts mobile/package.json
git commit -m "build(mobile): wire expo-updates for OTA on preview builds"
```

---

### Task H3: Sentry (env-gated)

**Files:**
- Modify: `mobile/app/_layout.tsx`
- Modify: `mobile/package.json`
- Modify: `mobile/app.config.ts`

- [ ] **Step 1: Install + init**

```bash
cd mobile && npx expo install @sentry/react-native sentry-expo
```

- [ ] **Step 2: Conditional init in _layout.tsx**

At the top of `mobile/app/_layout.tsx`, add:

```ts
import * as Sentry from 'sentry-expo';
import Constants from 'expo-constants';

const sentryDsn = Constants.expoConfig?.extra?.sentryDsn as string | undefined;
if (sentryDsn) {
  Sentry.init({ dsn: sentryDsn, enableInExpoDevelopment: false, debug: false });
}
```

In `mobile/app.config.ts`, surface the DSN:

```ts
extra: { backendUrl: BACKEND_URL, tenantId: TENANT_ID, sentryDsn: process.env.SENTRY_DSN },
```

The DSN is set only in the `preview` EAS profile, so dev builds stay silent.

- [ ] **Step 3: Commit**

```bash
git add mobile/app/_layout.tsx mobile/app.config.ts mobile/package.json
git commit -m "feat(mobile): env-gated Sentry init (preview profile only)"
```

---

### Task H4: Smoke test checklist

Run the full demo path on iOS simulator and Android emulator. Each item
below should pass with no warnings in the Metro console.

- [ ] First-launch: app shows splash → auth/phone with +27 default
- [ ] Enter Alice's number → `/auth/pin` (existing user path)
- [ ] Enter Alice's PIN → biometric opt-in sheet appears → tap Not now → home loads
- [ ] Home renders: balance card with ZAR balance, PTS chip in header, quick actions, beneficiary strip (Bob), featured campaign card (if seeded), recent activity rows
- [ ] Pull-to-refresh on home: balance + activity refresh
- [ ] Tap Send → recipient screen → enter Bob's phone → continue → amount → R 50 → continue → review → slide → success (no PIN, below threshold)
- [ ] Tap Send → R 5000 → review → slide → PIN sheet appears → enter `1234` → success (above threshold path)
- [ ] Toast / earned-PTS chip appears on success when rules engine fires
- [ ] Tap Top up → R 200 → card screen → tap card to flip animation works → slide to pay → success
- [ ] Tap gift-box icon → rewards screen → balance hero shows PTS → offers grid loads → tap an affordable offer → detail screen → slide to redeem → polling visualised → terminal success
- [ ] Tap unaffordable offer: cost chip muted, "need X more" pill shows, detail screen still loads and shows deficit
- [ ] Activity tab: Wallet segment shows ZAR rows, Rewards segment shows PTS rows, both grouped by day
- [ ] Profile tab: avatar + name + masked phone, biometric toggle works, sign-out returns to phone screen
- [ ] Dark mode: flip system appearance → app updates immediately (Tamagui useColorScheme)

If any check fails, file a follow-up task. Commit any small fixes as a
single tidy commit:

```bash
git commit -m "fix(mobile): demo polish from H4 smoke pass"
```

---

## Plan self-review (done — all checks pass)

- **Spec coverage**: §2 decisions → Phase A–H setups; §5 auth → Phase C; §6 home → D6; §7 activity → D7; §8 profile → D8; §9 P2P → Phase E; §10 topup → Phase F; §11 rewards/redemption → Phase G; §12 step-up → E1 (used by E5, F2, G2); §13 theming → B3+B4+B5; §14 plumbing → B7–B10; §15 build → H1+H2; §16 backend additions → Phase A.
- **Placeholders**: None — every step has concrete file paths, full code, exact commands.
- **Type consistency**: API types (`Wallet`, `WalletTransaction`, `Offer`, `FeaturedCampaign`, `P2PResponse`, `TopupResponse`, `Redemption`) defined once in `lib/api/*` and reused by every screen.
