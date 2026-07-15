# Pricing Admin Refinements — Implementation Plan (Epic 25)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development to
> implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Multi-band service-charge/commission schedules, form-based revise of changes-requested
proposals on the native config pages, a shared read-only config detail view (fixing the
approval drawer's mono-font mismatch), and a "Pricing" parent menu.

**Architecture:** Backend — the config-request `create` payload for pricing/commission becomes
`{ "bands": [ <full create dict>, … ] }`; propose validates the set, apply creates all bands in
one all-or-none transaction. Frontend — repeatable band rows in the create dialogs, a shared
`ConfigDetail` presentation reused by native "View" and the approval drawer, and changes-requested
items surfaced on native pages for form-based revise.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + pytest (backend); Next.js 16 App Router + shadcn
(admin-ui, tests deferred — typecheck + manual smoke).

**Spec:** `docs/superpowers/specs/2026-07-15-pricing-admin-refinements-design.md`

---

## File structure

Backend:
- `backend/app/modules/config_requests/apply.py` — add multi-band constants + `validate_band_payload`; loop apply.
- `backend/app/modules/config_requests/service.py` — propose/revise validate the band set for pricing/commission.
- `backend/app/modules/config_requests/router.py` — add optional `config_type` query filter to GET list.
- `backend/app/modules/config_requests/schemas.py` — allow `config_type` on the list; payload stays `dict`.
- Tests: `backend/tests/config_requests/test_multi_band.py` (new).

Frontend:
- `admin-ui/components/app-shell/sidebar.tsx`, `components/command-palette/command-palette.tsx` — Pricing parent + relabel.
- `admin-ui/app/(authenticated)/_components/config-detail.tsx` (new shared) — read-only sans presentation.
- `admin-ui/app/(authenticated)/pricing/_components/create-pricing-dialog.tsx`, `commissions/_components/create-commission-dialog.tsx` — repeatable bands + revise mode.
- `admin-ui/app/(authenticated)/{pricing,commissions,taxes,limits}/` pages — Changes-requested section + View action.
- `admin-ui/app/(authenticated)/config-requests/_components/request-detail-drawer.tsx` — drop JSON revise; render via `ConfigDetail`.
- `admin-ui/lib/api-endpoints.ts`, `lib/api-types.ts` — `config_type` filter param; band-set payload helper.

---

## Task 1: Multi-band payload validation (propose)

**Files:**
- Modify: `backend/app/modules/config_requests/apply.py`
- Test: `backend/tests/config_requests/test_multi_band.py`

- [ ] **Step 1: Write failing test** — a multi-band pricing propose is accepted and stored.

```python
# backend/tests/config_requests/test_multi_band.py
from uuid import UUID
import pytest
from httpx import AsyncClient
from app.shared.models import Tenant

pytestmark = pytest.mark.asyncio
MAKER = "11111111-1111-4000-8000-000000000001"
CHECKER = "22222222-2222-4000-8000-000000000002"

def _url(t: Tenant, s: str = "") -> str:
    return f"/api/v1/config-requests{s}?tenant_id={t.id}"

def _band(tenant_id, frm, to, fixed):
    return {
        "tenant_id": str(tenant_id), "transaction_type": "cash_in",
        "account_type": "financial_wallet", "currency": "ZAR",
        "user_type": "agent", "amount_from": frm, "amount_to": to, "fixed_fee": fixed,
    }

def _bands_body(tenant_id):
    return {"config_type": "pricing", "operation": "create",
            "payload": {"bands": [_band(tenant_id, "0", "100", "1"),
                                   _band(tenant_id, "100", None, "2")]}}

async def test_multi_band_propose_accepted(async_client, test_tenant, make_admin_token):
    maker = {"Authorization": f"Bearer {make_admin_token(roles=['platform-admin'], sub=MAKER)}"}
    resp = await async_client.post(_url(test_tenant), json=_bands_body(test_tenant.id), headers=maker)
    assert resp.status_code == 201, resp.text
    assert len(resp.json()["payload"]["bands"]) == 2
```

- [ ] **Step 2: Run — expect FAIL** (overlap/validation or 422 for unknown "bands" shape).

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/config_requests/test_multi_band.py::test_multi_band_propose_accepted -q`

- [ ] **Step 3: Implement `validate_band_payload` in apply.py.**

```python
# apply.py — add near build_create_schema
MULTI_BAND_TYPES = {CONFIG_TYPE_PRICING, CONFIG_TYPE_COMMISSION}

def validate_band_payload(config_type: str, payload: dict[str, Any]) -> list[BaseModel]:
    """Validate a multi-band create payload ({"bands":[row,...]}) or a single dict.

    Returns the validated create-schema models (one per band). Raises 422 on a
    malformed row, mismatched shared scope, or overlapping/mis-ordered bands.
    """
    if config_type in MULTI_BAND_TYPES and isinstance(payload.get("bands"), list):
        rows = payload["bands"]
    else:
        rows = [payload]  # legacy single-band
    if not rows:
        raise AppHTTPException(422, "config_request_invalid_payload", "At least one band is required.")
    models = [build_create_schema(config_type, r) for r in rows]
    _assert_shared_scope(models)
    _assert_bands_ordered(models)
    return models

def _assert_shared_scope(models: list[BaseModel]) -> None:
    """All bands must share (transaction_type, account_type, currency, user_type)."""
    keys = {(m.transaction_type, m.account_type, m.currency, m.user_type) for m in models}  # type: ignore[attr-defined]
    if len(keys) > 1:
        raise AppHTTPException(422, "config_request_band_scope_mismatch",
                               "All bands must share the same service, currency and user type.")

def _assert_bands_ordered(models: list[BaseModel]) -> None:
    """Bands must be ascending and non-overlapping; only the last may be open-ended."""
    bands = sorted(models, key=lambda m: (m.amount_from is None, m.amount_from or 0))  # type: ignore[attr-defined]
    for i, m in enumerate(bands):
        if m.amount_to is not None and m.amount_from is not None and m.amount_to <= m.amount_from:  # type: ignore[attr-defined]
            raise AppHTTPException(422, "config_request_band_invalid", "amount_to must exceed amount_from.")
        if i > 0:
            prev = bands[i - 1]
            if prev.amount_to is None or (m.amount_from is not None and m.amount_from < prev.amount_to):  # type: ignore[attr-defined]
                raise AppHTTPException(422, "config_request_band_overlap", "Bands must not overlap.")
```

- [ ] **Step 4: Wire propose to use it.** In `service.py::propose_config_change`, for a `create`, replace the single `build_create_schema` + tenant check with: if `config_type in MULTI_BAND_TYPES` → `validate_band_payload(config_type, payload)` and store `payload = {"bands": [m.model_dump(mode="json") for m in models]}`; assert every band's `tenant_id == tenant_id`. Else keep current single-dict path.

- [ ] **Step 5: Run — expect PASS.**

Run: `python -m pytest tests/config_requests/test_multi_band.py::test_multi_band_propose_accepted -q`

- [ ] **Step 6: Add validation tests** — overlapping bands → 422 `config_request_band_overlap`; scope mismatch → 422 `config_request_band_scope_mismatch`. Run them, expect PASS.

- [ ] **Step 7: Commit.** `git commit -m "feat(config-requests): validate multi-band pricing/commission payloads"`

---

## Task 2: Multi-band apply (all-or-none)

**Files:** Modify `backend/app/modules/config_requests/apply.py`; Test `test_multi_band.py`.

- [ ] **Step 1: Failing test** — approving a 2-band pricing request creates 2 rows; a bad band creates 0 (rollback).

```python
async def test_multi_band_apply_creates_all_rows(async_client, db_session, test_tenant, make_admin_token):
    from sqlalchemy import select, func
    from app.shared.models import PricingConfig
    maker = {"Authorization": f"Bearer {make_admin_token(roles=['platform-admin'], sub=MAKER)}"}
    checker = {"Authorization": f"Bearer {make_admin_token(roles=['platform-admin','config-approver'], sub=CHECKER)}"}
    rid = (await async_client.post(_url(test_tenant), json=_bands_body(test_tenant.id), headers=maker)).json()["id"]
    resp = await async_client.post(_url(test_tenant, f"/{rid}/approve"), headers=checker)
    assert resp.status_code == 200, resp.text
    n = (await db_session.execute(select(func.count()).select_from(PricingConfig)
         .where(PricingConfig.tenant_id == test_tenant.id))).scalar_one()
    assert n == 2
```

- [ ] **Step 2: Run — expect FAIL** (apply only creates one / errors on the `bands` payload).

- [ ] **Step 3: Update `apply_config_request`** — for a create, use `validate_band_payload` and loop:

```python
if request.operation == CONFIG_OP_CREATE:
    models = validate_band_payload(request.config_type, request.payload or {})
    for schema in models:
        await create_fn(session, schema, admin=admin, ip_address=ip_address)
else:
    ...  # unchanged delete
```

All bands share the caller's transaction (the create services stage rows; the single commit
that persists the request→APPLIED transition persists them all — any failure rolls back all).

- [ ] **Step 4: Run — expect PASS.** Both this and the propose tests.

- [ ] **Step 5: All-or-none test** — a set whose 2nd band collides with an existing row rolls back the 1st (count stays 0, request not APPLIED). Run, expect PASS.

- [ ] **Step 6: Back-compat test** — a legacy single-dict pricing payload still applies as one row. Run, expect PASS.

- [ ] **Step 7: Commit.** `git commit -m "feat(config-requests): apply multi-band creates atomically"`

---

## Task 3: config_type filter on GET /config-requests

**Files:** Modify `router.py`, `service.py` (list). Test `test_multi_band.py` (or existing maker-checker test).

- [ ] **Step 1: Failing test** — `GET /config-requests?tenant_id=..&config_type=commission` returns only commission requests.
- [ ] **Step 2: Run — expect FAIL** (param ignored / 422).
- [ ] **Step 3: Add `config_type: str | None = None` query param to `get_requests`; thread to `list_config_requests(session, tenant_id, status=..., config_type=...)`; add `ConfigChangeRequest.config_type == config_type` to the query when set.**
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit.** `git commit -m "feat(config-requests): filter list by config_type"`

---

## Task 4: `mypy` + `ruff` + focused suite gate (backend)

- [ ] Run `cd backend && source .venv/bin/activate && ruff check . && mypy app/ && python -m pytest tests/config_requests -q`. All clean/green. Fix anything. Commit if fixes.

---

## Task 5: Menu — Pricing parent + relabel (frontend)

**Files:** `components/app-shell/sidebar.tsx`, `components/command-palette/command-palette.tsx`.

- [ ] Add a collapsible **Pricing** parent group to the `CONFIG` nav with children Service charges (`/pricing`, relabel from "Pricing"), Commission (`/commissions`), Taxes (`/taxes`). Follow the existing `NavItem` shape; if the sidebar has no group concept, add a minimal `NavGroup` (label + icon + children) rendered as a header with indented children, active-state via `usePathname`. Update command-palette `NAV` labels to match.
- [ ] `npm run typecheck` clean. Manual: sidebar shows Pricing ▸ {Service charges, Commission, Taxes}; Limits + Config requests still top-level.
- [ ] Commit. `git commit -m "feat(admin-ui): group Service charges/Commission/Taxes under a Pricing menu"`

---

## Task 6: Shared `ConfigDetail` read-only view (frontend)

**Files:** Create `admin-ui/app/(authenticated)/_components/config-detail.tsx`.

- [ ] Build a client component `ConfigDetail({ configType, data })` that renders a labeled field
  list in the app's **sans** typography (no `font-mono` except a raw-id fallback). For pricing/
  commission it accepts either a single row or a `{bands:[...]}` payload and renders the shared
  scope once + a small bands table (from/to/fixed/variable%/cap). For tax/limit it renders the
  flat fields. Hide `tenant_id`. Reuse existing `formatAmount`, `Badge`, `UserTypeBadge`.
- [ ] `npm run typecheck` clean.
- [ ] Commit. `git commit -m "feat(admin-ui): shared read-only ConfigDetail view"`

---

## Task 7: Approval drawer — render via ConfigDetail; drop JSON revise (frontend)

**Files:** `config-requests/_components/request-detail-drawer.tsx`.

- [ ] Replace the mono payload block + `renderValue` with `<ConfigDetail configType={request.config_type} data={request.payload} />`. Replace the maker-line `font-mono` with sans (keep short-id fallback plain). Remove the payload textarea / `reviseMode` / `onRevise` (maker no longer edits here). Keep checker Approve / Request-changes (comment). Drawer becomes read-only for makers.
- [ ] `npm run typecheck` clean. Manual: drawer text matches the admin sans font; no JSON editor.
- [ ] Commit. `git commit -m "fix(admin-ui): render proposed change via ConfigDetail; sans font; drop JSON revise"`

---

## Task 8: Multi-band create dialogs + revise mode (frontend)

**Files:** `pricing/_components/create-pricing-dialog.tsx`, `commissions/_components/create-commission-dialog.tsx`.

- [ ] Convert the single band inputs into a repeatable **bands** list (state: `bands: BandRow[]`), each row from/to/fixed/variable%/cap with Add/Remove; shared scope (service/currency/user-type, +fee_inclusive for pricing) stays single. Client validation: ascending, non-overlapping, last open-ended, ≥1 band. Build the propose payload as `{ bands: bands.map(row => ({ ...scope, ...row })) }` and submit via `proposeConfigChange`.
- [ ] Add a **revise mode**: the dialog accepts optional `reviseRequest?: ConfigChangeRequest` — when set, it pre-fills scope + bands from `reviseRequest.payload.bands`, the submit button reads "Resubmit", and it calls `reviseConfigRequest(tenant, id, payload)` then `resubmitConfigRequest(tenant, id)` instead of propose.
- [ ] `npm run typecheck` clean. Manual: create a 2-band pricing config → one PENDING request with 2 bands.
- [ ] Commit. `git commit -m "feat(admin-ui): multi-band pricing/commission dialogs + revise mode"`

---

## Task 9: Native pages — Changes-requested section + View action (frontend)

**Files:** `pricing/page.tsx`, `commissions/page.tsx`, `taxes/page.tsx`, `limits/page.tsx` (+ their tables).

- [ ] On each page, fetch `listConfigRequests(tenantId, "CHANGES_REQUESTED", <config_type>)` and render a "Changes requested" section above the table: one card per request showing the ConfigDetail summary + the checker's latest comment + an **Edit & resubmit** button that opens the create dialog in revise mode (Task 8). Gate the button to the maker (`session.user.id === maker_admin_id`).
- [ ] Add a **View** action per table row opening a drawer/dialog with `<ConfigDetail>` for that live config.
- [ ] `npm run typecheck` clean. Manual smoke of the full loop: propose multi-band → (as admin-approver) request changes → item appears on Service charges page → (as admin-test) Edit & resubmit via form → back to PENDING in the queue → approve → rows created.
- [ ] Commit. `git commit -m "feat(admin-ui): changes-requested editing + View on native config pages"`

---

## Task 10: Final verification

- [ ] Backend: `ruff check . && mypy app/ && python -m pytest tests/config_requests tests/pricing tests/commissions tests/taxes -q` green.
- [ ] Frontend: `npm run typecheck && npm run build` clean.
- [ ] `code-review` agent on the full diff; fix findings.
- [ ] Commit any fixes; push.

---

## Self-review notes

- Spec coverage: A(menu)=T5, B(multi-band)=T1/T2/T8, C(revise relocation)=T3/T7/T8/T9, D(view)=T6/T9, E(font)=T6/T7. ✓
- Back-compat: legacy single-dict payloads still apply (T2 step 6).
- Types consistent: `validate_band_payload`, `MULTI_BAND_TYPES`, `{bands:[...]}` used identically across tasks.
- Frontend tests deferred per repo policy — verification is typecheck/build + manual smoke.
