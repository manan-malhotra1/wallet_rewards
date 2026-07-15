# Pricing Admin Refinements — Design (Epic 25)

> **Status:** Approved 2026-07-15. Builds on Pricing v2 (Epics 19–24).
> **Prereqs shipped:** config-requests maker-checker (Epic 22), pricing/commission/tax
> admin screens + review UI (Epic 24), admin & user display names (this session).

## Problem

Three gaps surfaced while using the Epic 24 admin UI:

1. **Single band only.** A service charge / commission can only be created with one
   amount band at a time. Operators need a *schedule* — several bands, each with its
   own fixed + variable% + cap — defined and approved as a unit.
2. **Revise flow is wrong.** A checker who requests changes leaves the proposal in the
   config-requests queue, where the maker edits raw JSON. It should instead surface on
   the config's *native* page (Service charges / Commission / Taxes / Limits) as
   "Changes requested", and the maker should edit it through the **normal form**, not JSON.
3. **Flat menu.** Pricing, Commission, Taxes are separate top-level items; they should be
   grouped under a **Pricing** parent.

## Decisions (locked)

- Multi-band applies to **service charges (pricing) and commission** only. Taxes are keyed
  per (tenant, currency) with no bands; limits are unchanged.
- Multi-band propose payload is `{ "bands": [ {row}, … ] }`; on **approval** all bands are
  applied in **one transaction — all-or-none**. A single-band config is a one-element list.
- Editing an already-**applied** multi-band schedule (regrouping live rows into one form) is
  **phase 2**. This epic covers multi-band **creation** and form-based **revise** of a
  `CHANGES_REQUESTED` proposal.
- Frontend automated tests remain deferred (typecheck + build + manual smoke). Backend gets tests.

## A. Menu restructure

Sidebar gains a collapsible **Pricing** parent grouping three existing routes as children:
- **Service charges** — today's `/pricing` (relabeled from "Pricing").
- **Commission** — `/commissions`.
- **Taxes** — `/taxes`.

Limits and the config-requests approval queue stay top-level (they span all config types).
Routes are unchanged — only nav grouping + the label change. Command-palette entries updated
to the new labels. `components/app-shell/sidebar.tsx` gains a parent/children nav shape (or a
labeled group) following the existing `NavItem` pattern.

## B. Multi-band configs

### Frontend (create dialogs: pricing + commission)
- Shared scope fields at top: service, currency, user type (+ `fee_inclusive` for pricing).
- A repeatable **bands** list; each row: `amount_from`, `amount_to`, `fixed`, `variable%`, `cap`.
  "Add band" / remove-row. Per-band live preview.
- Client validation before submit: within a config, bands must be ascending and
  non-overlapping (`amount_to` of one ≤ `amount_from` of the next); each band's `amount_to`
  (when set) > its `amount_from`; the final band may be open-ended (`amount_to` empty). At
  least one band required.

### Backend (config-requests)
- `ConfigChangeProposeRequest.payload` for `config_type in {pricing, commission}` + `create`
  is `{ "bands": [ row, … ] }`, where each row is that type's create-schema fields **minus**
  the shared scope OR each row is a full create dict — implementation picks one and documents
  it; the shared scope (tenant/service/currency/user_type, and `fee_inclusive` for pricing)
  is common to all bands. Simplest: each element is a complete create-schema dict; the propose
  validator validates every element and asserts they share scope + form a valid band set.
- `apply_config_request` for a pricing/commission `create` with a `bands` payload iterates and
  calls `create_pricing_config` / `create_commission_config` for **each** band inside the single
  approval transaction — any failure rolls back all (all-or-none).
- Back-compat: a legacy flat single-dict payload is treated as a one-band set.
- Taxes/limits/wallet_limit payloads unchanged.
- Server-side band validation (order + non-overlap) mirrors the client rule; reject with a 422.

## C. Changes-requested → native page, form-based revise

### Queue vs native split
- **config-requests page** = the **checker's queue**: default shows `PENDING`. `CHANGES_REQUESTED`
  items no longer appear here.
- **Native pages** (Service charges / Commission / Taxes / Limits) each fetch their own
  `CHANGES_REQUESTED` proposals (config-requests filtered by `status` + `config_type`) and render
  them at the top as "Changes requested" cards showing the checker's latest comment.

### Maker edit loop (form-based)
1. Maker clicks **Edit & resubmit** on a "Changes requested" card.
2. The **native create dialog opens in revise mode**, pre-filled from the proposal payload
   (all bands for pricing/commission).
3. Maker edits via **UI fields only** (no JSON).
4. **Resubmit** = `PATCH /config-requests/{id}` (revised payload) then
   `POST /config-requests/{id}/resubmit` → status back to `PENDING`.
5. The item leaves the native page and reappears in the checker queue.

### Drawer changes
- Remove the **JSON textarea revise** from `request-detail-drawer`.
- The drawer stays: read-only payload + review thread; **checker** actions (approve /
  request-changes with mandatory comment) remain. Maker no longer edits in the drawer.

## D. View details for pricing / commission / taxes

Today the native tables list rows but there is no way to see a config's full detail.
Add a **View** affordance (row click or a "View" action) on each native page that opens a
read-only detail panel (drawer) showing the config's fields — and, for pricing/commission,
all bands of the schedule grouped together — in the app's normal typography.

The same read-only presentation renders the **proposed change** in the config-request
approval drawer (replacing the raw JSON/mono block): a shared `ConfigDetail` view that takes
a config-or-payload and renders a labeled, readable field/band list. This unifies "view a
live config" and "view a proposed change" and is what the checker reads before approving.

## E. Typography fix (approval drawer)

The approval drawer renders the proposed change, ids, and the maker line in `font-mono`
(GeistMono), which clashes with the sans (GeistSans) admin pages. Fix: render the proposed
change and metadata in the standard **sans** typography via the shared `ConfigDetail` view
(D); reserve `font-mono` only for genuinely code-like tokens (e.g. a raw id fallback), matching
the rest of the admin UI. No new font — use the existing design-system classes/tokens.

## Backend surface summary

- `config_requests/schemas.py` — payload typing allows the `{bands:[…]}` shape.
- `config_requests/apply.py` — batch create for pricing/commission; band-set validation.
- `config_requests/service.py` / router — unchanged workflow; propose/revise accept the band set.
- Optional: add a `config_type` filter to `GET /config-requests` so native pages fetch only
  their own `CHANGES_REQUESTED` items (else filter client-side).

## Frontend surface summary

- `sidebar.tsx` + `command-palette.tsx` — Pricing parent + relabel.
- pricing & commission create dialogs — repeatable bands + revise/pre-fill mode.
- pricing / commission / tax / limits pages — "Changes requested" section + Edit-&-resubmit
  wiring to the dialog in revise mode; **View** action opening the shared `ConfigDetail`.
- New `ConfigDetail` read-only presentation (sans typography, grouped bands) reused by the
  native "View" and the approval drawer's proposed-change block.
- `request-detail-drawer.tsx` — drop JSON revise; render proposed change via `ConfigDetail`
  (sans, not mono); view-only for makers.
- `lib/api-types.ts` / `lib/api-endpoints.ts` — band-set payload types; reuse existing
  propose/revise/resubmit wrappers.

## Testing

Backend (pytest):
- Multi-band propose → approve creates **N** rows in one transaction.
- All-or-none: a bad band in the set rolls back the whole apply (no partial rows).
- Band-set validation: overlapping / descending bands rejected (422) at propose.
- Revise loop: changes-requested → PATCH (revised bands) → resubmit → PENDING → approve applies
  the revised set.
- Back-compat: a legacy single-dict payload still applies as one band.

Frontend: typecheck + build + manual smoke (propose multi-band → request-changes → edit on
native page via form → resubmit → approve).

## Out of scope (phase 2)

- Editing/regrouping an already-**applied** multi-band schedule from the native table.
- Per-band delete of a live schedule (delete stays per-row as today).
