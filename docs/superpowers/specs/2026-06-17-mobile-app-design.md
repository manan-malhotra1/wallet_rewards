# Sasai Wallet Mobile App — Design Spec

**Date:** 2026-06-17
**Author:** Brainstorm session with Manan
**Status:** Approved — ready for implementation planning
**Tracking:** New top-level directory `mobile/` in this repo; net-new module alongside `backend/`, `admin-ui/`, `mobile-simulator/`

---

## 1. Goal & scope

Build a polished, demo-ready iOS + Android mobile app that showcases the Sasai Wallet
product to investors and partners. The app talks to the existing backend (staging
environment) and exercises the primary user-facing flows: phone-based login, ZAR
wallet, P2P send, top-up (mock card), rewards points, and redemption.

**Out of scope** (deferred to a later phase, not Phase 2 of this app):

- KYC / ID verification flow
- Real card-processor integration for top-up
- App Store / Play Store production launch
- Multi-currency wallets beyond ZAR + PTS
- Cross-border remittance
- Push notifications (the rewards-earned moment uses an in-app toast instead)
- Multi-tenant tenant switcher (single tenant `Sasai-ZA` only)
- Frontend automation tests (per `coding-guidelines.md` §4)

---

## 2. Locked decisions

| Decision | Value | Rationale |
|---|---|---|
| Audience | Investor / partner demo | Polish > coverage; happy paths matter most |
| Platforms | iOS + Android | Single codebase via Expo |
| Tech stack | Expo SDK 52 (React Native + TypeScript) | Familiar React/TS world; OTA updates; EAS Build |
| Design system | Tamagui | Polished components out of the box; light + dark theme tokens |
| Navigation | Expo Router (file-based) | Matches Next.js mental model the team already has |
| Data layer | TanStack Query | Caching, invalidation, mutations |
| Default country code | +27 South Africa | Matches the seeded `Sasai-ZA` tenant |
| Wallet displayed | One ZAR financial wallet + one PTS points account | Matches the seed |
| P2P recipient | Phone number entry | Most natural; backend already normalizes phones |
| Top-up mechanism | Mock card form (visual only) | No PCI surface; backend uses `operator_adjustment` |
| KYC | Skipped entirely | Phase-2 concern |
| Theme | Light + dark, follow system | Tamagui supports both natively |
| PIN length | 4 digits | Standard for this market; matches seed default `1234` |
| Biometrics | Opt-in prompt after first successful PIN entry | Demo-friendly polish moment |

---

## 3. Branding

- **Logo**: teal swoosh "S" mark + lowercase navy "sasai" wordmark
- **Primary**: navy `#144989`
- **Accent**: teal `#48C2CF`
- **Typography**: Inter (regular / medium / semibold / bold)
- **Geometry**: rounded-2xl/3xl cards; generous whitespace; spacing on a `4` multiple
- **Motion**: subtle entrance staggers; press-scale `0.97` on interactive primitives;
  springy success animations

---

## 4. Project structure

```
mobile/
  app.json
  app.config.ts                  # env-driven config (staging vs local backend)
  eas.json                       # development / preview / production profiles
  tamagui.config.ts              # Sasai light + dark themes
  app/                           # Expo Router routes
    _layout.tsx                  # root: providers (Tamagui, Query, fonts), splash
    index.tsx                    # redirect → /auth/phone or /(tabs)/home
    auth/
      phone.tsx                  # country code + phone
      otp.tsx                    # 6-digit OTP (new users)
      set-pin.tsx                # PIN selection (new users)
      pin.tsx                    # PIN entry (returning users)
    (tabs)/
      _layout.tsx                # floating glass tab bar (Home · Activity · Profile)
      home.tsx
      activity.tsx
      profile.tsx
    p2p/
      recipient.tsx
      amount.tsx
      review.tsx
      success.tsx
    topup/
      amount.tsx
      card.tsx
      success.tsx
    rewards/
      index.tsx                  # PTS hero + offer grid + history peek
      [offerId].tsx              # offer detail + redemption confirm
      success.tsx
  components/
    ui/
      BalanceCard.tsx            # hero ZAR card w/ gradient + mask toggle
      RewardsCard.tsx            # PTS hero card
      ActionChip.tsx             # pill-shaped quick action
      BeneficiaryStrip.tsx       # horizontal carousel of recent recipients
      CampaignBanner.tsx         # featured campaign
      ActivityRow.tsx            # one row in the activity list
      SlideToConfirm.tsx         # slide-to-act gesture button
      PinChallengeSheet.tsx      # step-up PIN entry sheet
      OfferCard.tsx              # redemption offer card
      SegmentControl.tsx
    forms/
      PhoneInput.tsx             # country picker + e.164 input
      OtpInput.tsx               # 6-box paste-friendly input
      PinInput.tsx               # 4-box keypad input
      AmountInput.tsx            # big-number currency input + quick chips
  lib/
    api/
      client.ts                  # typed fetch wrapper + error mapping
      auth.ts
      wallet.ts
      payments.ts
      redemption.ts
      catalog.ts
    auth.ts                      # session + biometric flow
    storage.ts                   # expo-secure-store wrapper
    query.ts                     # TanStack Query client + qk factory
    step-up.ts                   # useStepUpAware hook
    format.ts                    # currency / phone / date formatters
    theme.ts                     # tamagui theme helpers
  assets/
    sasai-logo.svg
    icon.png
    splash.png
    fonts/Inter-*.ttf
```

Routes split into three groups: `auth/` (pre-login), `(tabs)/` (post-login shell with
bottom tabs), and modal-style flows `p2p/` `topup/` `rewards/` that push above the tabs.

---

## 5. Auth flow

### 5.1 Phone screen (`auth/phone.tsx`)

- Country picker (Tamagui `Sheet`, searchable list, defaults +27)
- Phone input in E.164-friendly format
- On Continue, app calls **new endpoint** `POST /identity/auth/start` with `{ phone_e164 }`
  → response is `{ status: "needs_otp" | "needs_pin" }`
- Route to `auth/otp.tsx` or `auth/pin.tsx` accordingly

### 5.2 OTP screen (`auth/otp.tsx`) — new users

- 6-digit boxed input; paste-fills all six; auto-submits on completion
- Calls `POST /identity/otp/verify`
- "Didn't get a code?" with 30-second resend countdown
- For the demo, the backend prints the OTP to logs (Twilio wiring is later)

### 5.3 Set-PIN screen (`auth/set-pin.tsx`) — new users

- Two-step: enter PIN, confirm PIN
- Calls `POST /identity/pin/set`; receives a session token
- Stores token in `expo-secure-store`; routes to `/(tabs)/home`

### 5.4 PIN screen (`auth/pin.tsx`) — returning users

- 4-digit keypad-style input
- Calls `POST /identity/auth/pin`
- On 5 consecutive wrong entries, the backend lockout fires; the app shows a
  friendly cooldown screen with a "back" affordance
- After **first successful PIN** entry post-install, show the biometric opt-in sheet:
  "Use Face ID / Touch ID / fingerprint next time?" Stored as a boolean +
  a stashed bcrypt-verified flag in secure store

### 5.5 Session resume

- On launch, if a session token exists and is non-expired → straight to `/(tabs)/home`
- If expired (401 + `session_expired`) → drop the token and route to `auth/pin.tsx`
  with the cached `last_phone_e164` prefilled (non-secure storage)

---

## 6. Home screen (`(tabs)/home.tsx`)

Layout, top to bottom:

1. **Top bar**: profile avatar (left) · Sasai logo (center) · notification bell (right,
   placeholder for now) · gift-box icon with PTS count badge (right). Tap gift box →
   `/rewards`.
2. **BalanceCard** — full-bleed gradient card (navy → teal, ~15deg, subtle noise
   texture), rounded-3xl. Shows:
   - "ZAR · Available"
   - Balance amount in large weight-700
   - Masked account suffix (`•• •• •• 2841`) and a small Sasai mark
   - Eye toggle in the corner to mask/unmask balance (Tamagui animation)
3. **Quick action chips** — pill-shaped circular buttons in a row: Send · Top up ·
   Scan QR · More. QR + More are visual-only placeholders; Send pushes
   `/p2p/recipient`, Top up pushes `/topup/amount`.
4. **"Send again" beneficiary carousel** — horizontal scroll of recent recipients
   from the user's P2P history, each with a color-hashed initial avatar. Trailing
   `+ Add` chip starts a fresh P2P. Empty state: collapses cleanly (no ghost slot).
5. **Featured campaign card** — pulls top active campaign for the user. Tap deep-links
   into the matching primary action (e.g., a top-up campaign → `/topup/amount` with
   the suggested amount preselected). Collapses gracefully if no campaign is active.
6. **Recent activity preview** — last 4–5 entries from `recent_transactions` on
   `GET /me/wallet`, with type icons (⬆ debit · ⬇ credit · ✨ reward · 🎟 redemption),
   relative time, +/- amount color-coded teal/muted-red. "See all" pushes
   `(tabs)/activity`.

**Animations on first paint**: balance card slides up; chips stagger in; activity
rows fade in sequentially.

---

## 7. Activity tab (`(tabs)/activity.tsx`)

- Top: Tamagui `SegmentControl` — `Wallet | Rewards`
- **Wallet segment**: ledger entries against the user's ZAR account
- **Rewards segment**: ledger entries against the user's PTS account, labeled with
  the originating campaign/rule for accruals and the redeemed offer for redemptions
- Rows grouped by day (Today · Yesterday · `DD MMM`)
- Pull-to-refresh invalidates `qk.wallet()`
- Tap a row → opens a detail Tamagui `Sheet` showing counterparty, timestamp,
  reference, idempotency key, and a "Report a problem" footer link (visual only)

All entries come from the existing `recent_transactions` field on `GET /me/wallet`.

---

## 8. Profile tab (`(tabs)/profile.tsx`)

Minimal: avatar, name, phone (masked), "Use biometrics" toggle, theme toggle
(system / light / dark), "Sign out" CTA. Sign out clears secure storage and routes
to `auth/phone.tsx`.

---

## 9. P2P send flow

A three-screen + sheet flow. A 3-dot step indicator persists across the first three
screens.

### 9.1 Recipient (`p2p/recipient.tsx`)

- Country code + phone input (same component as login)
- Below: the same "Send again" carousel from home (in case the user came in cold)
- On Continue, app calls `POST /identity/auth/start` reusing the same phone-lookup
  endpoint to resolve the recipient. If unknown user → inline error
  *"No Sasai user with that number yet."*

### 9.2 Amount (`p2p/amount.tsx`)

- Big centered `R 0.00` input + numeric keyboard
- Quick chips below: `R 50 · R 100 · R 200 · R 500` (tap to fill, tap again to clear)
- Above the amount: `From: ZAR Wallet · R 12,450.00 available` pill (muted)
- Optional note (60-char limit)
- Continue disabled while `amount <= 0` or `amount > available`
- Insufficient balance → inline shake + "Insufficient balance. Top up?" with a
  one-tap shortcut to `/topup/amount`

### 9.3 Review (`p2p/review.tsx`)

- Recipient block: initial-bubble avatar + first name + masked phone
- Amount in display weight; "Fee R 0.00" in muted text below (pricing engine output)
- Note (if entered)
- "From: ZAR Wallet" block
- **SlideToConfirm** primitive at the bottom: *"Slide to send R 250.00"*

### 9.4 Slide → server roundtrip → maybe PIN sheet

- App generates a fresh `Idempotency-Key` (UUID) when the user lands on Review
- On slide, the button transitions to a `~300ms` "checking…" state, then calls
  `POST /payments/p2p` **without** `pin`
- Routes per **Section 13 — Step-up PIN handling**:
  - `200` → success (Section 9.5)
  - `401 step_up_required` → `PinChallengeSheet` slides up → on submit, re-call same
    endpoint with **same** `Idempotency-Key` + `pin` attached → success or wrong-PIN
  - other errors → friendly toast + stay on Review

### 9.5 Success (`p2p/success.tsx`)

- Springy teal-on-navy checkmark animation
- "R 250.00 sent to Bob"
- Two CTAs: `Done` (replaces stack → home with balance count-up animation) and
  `Send another` (pops back to `p2p/recipient.tsx`)
- If the response includes `earned_points > 0`, a top-edge toast slides in:
  **"+10 PTS earned · See rewards"** → tap deep-links to `/rewards`

**Backend dependency**: extend `P2PResponse` with `earned_points: int | null` so the
toast doesn't require a separate round-trip.

---

## 10. Top-up flow (mock card)

### 10.1 Amount (`topup/amount.tsx`)

- Same big-amount input style as P2P
- Quick chips: `R 100 · R 200 · R 500 · R 1,000`
- "Topping up: ZAR Wallet" pill above
- Continue

### 10.2 Card (`topup/card.tsx`)

- Visual mock card at the top: Tamagui `LinearGradient` card with placeholder Visa
  mark, chip icon, demo card number `4242 •••• •••• 4242`. Horizontal-tap flips it
  to show the CVV side.
- Pre-filled form below (disabled fields): `Demo Cardholder · 12/29 · 123`
- "Save card for next time" toggle (cosmetic; remembered locally)
- **SlideToConfirm** primitive: *"Slide to pay R 500.00"*
- On slide → same try-then-PIN flow as P2P, calling **new endpoint**
  `POST /payments/topup`. Backend internally credits the user's ZAR account via
  `operator_adjustment` (no real card processor).

### 10.3 Success (`topup/success.tsx`)

- Same checkmark spring animation
- "R 500.00 added to your wallet"; new balance below
- `Done` returns to home with the balance count-up animation
- If a top-up campaign fired, the same earned-PTS toast pattern from P2P fires here

---

## 11. Rewards + redemption flow

### 11.1 Rewards screen (`rewards/index.tsx`)

Triggered by the gift-box icon on home.

- **RewardsCard hero** — teal-dominant gradient card showing
  - `Your points · 340 PTS`
  - `≈ R 34.00 redeem value` (display-only conversion at fixed `1 PTS = R 0.10`)
- **Filter chips** — `All · Airtime · Vouchers · Data` driven by offer `category`
- **Offers grid** — two-column grid of `OfferCard`s from `GET /catalog/me/summary`.
  Each card: icon/image · offer name · face value (ZAR) · PTS cost. Unaffordable
  offers render with a muted cost chip + corner pill "Need 60 more PTS". Still
  tappable (the detail screen handles the deficit).
- **History peek** — last 3 PTS-account entries from `recent_transactions`; "See all"
  deep-links to `(tabs)/activity` with the Rewards segment active.

### 11.2 Offer detail (`rewards/[offerId].tsx`)

- Offer hero image / icon, name, description, terms (muted)
- "You'll spend **100 PTS** — your balance after: **240 PTS**"
- Recipient field (for airtime / data / voucher categories): defaults to the user's
  own phone, tap to change (same `PhoneInput` as login + P2P). Enables a small
  showcase moment ("send your friend airtime with your points").
- **SlideToConfirm** primitive: *"Slide to redeem"*

### 11.3 Slide → initiate → maybe PIN → confirm → poll → terminal

This is the only flow with multi-step backend orchestration. Single shared
`useStepUpAware` hook still handles the PIN sheet.

1. App calls `POST /redemption/initiate` with
   `{ offer_id, recipient_phone, idempotency_key }`
   → backend reserves PTS, returns `redemption_id` in `pending`
2. App calls `POST /redemption/{id}/confirm` **without** `pin`. Server runs
   `enforce_step_up`. Three outcomes:
   - `200 completed` → straight to success
   - `401 step_up_required` → PIN sheet → retry confirm with same id + pin
   - `200 pending` (provider still working) → polling phase
3. **Polling phase** — `GET /redemption/{id}` every 1.5s for up to 8s with a
   Tamagui pulse animation on the offer image; status text "Sending your airtime…"
4. Terminal:
   - `completed` → success screen with reference + "Done" CTA
   - `failed` → friendly failure with one-tap retry (new idempotency key,
     fresh `/initiate`)

---

## 12. Step-up PIN handling (cross-cutting)

Applies to: `POST /payments/p2p`, `POST /payments/topup`, `POST /redemption/{id}/confirm`.

**Backend contract** (verified in code):

- Each request schema has an optional `pin: str | None` field
- Service calls `enforce_step_up(tenant, user, amount, currency, action, pin)`:
  - Below the policy threshold → no-op
  - At/above threshold + no PIN → raises `StepUpRequired` → `401 step_up_required`
  - At/above threshold + wrong PIN → raises `InvalidStepUpPin` → `401 invalid_step_up_pin`
  - At/above threshold + correct PIN → proceeds

**Mobile try-then-PIN pattern**:

```
1. Generate Idempotency-Key.
2. Call endpoint WITHOUT pin.
3. On 200/201 → success path.
4. On 401 step_up_required:
     → PinChallengeSheet opens.
     → User enters PIN.
     → Re-call SAME endpoint with SAME Idempotency-Key + pin attached.
     → On 200/201 → success.
     → On 401 invalid_step_up_pin → shake; clear input; remain on sheet.
                                    Backend handles 5-fail lockout; mirror with
                                    friendly cooldown screen.
     → Other → close sheet; toast error.
5. Any other error from step 2 → toast error.
```

**Implementation rules:**

- `useStepUpAware(endpoint)` hook in `lib/step-up.ts` is the single home for this
  logic; P2P, topup, redemption all consume it
- `PinChallengeSheet` is the single PIN UI; identical across flows
- Idempotency-Key is generated **once** per logical action and reused across retries
- The API client must filter `pin` out of any request-debug surface

---

## 13. Theming

### Color tokens (Tamagui `tamagui.config.ts`)

```
sasaiNavy:   #144989   (primary)
sasaiTeal:   #48C2CF   (accent, light bg)
sasaiTealDk: #2EA5B2   (accent, dark bg)
ink:         #0B1726   (primary text on light)
inkInverse:  #E8F0F8   (primary text on dark)
muted:       #6A7682   (secondary text)
surfaceLt:   #FFFFFF
surfaceDk:   #0E1A2B
success:     #22C55E
warn:        #F59E0B
error:       #EF4444
```

Two registered themes: `light` (default) and `dark`. `useColorScheme()` at root
selects the active theme. Brand gradient (navy → teal) is a reusable component, not
a token, to keep angle/stops centralized.

### Typography

- **Inter** — regular / medium / semibold / bold
- Loaded via `expo-font` in `_layout.tsx`
- Wired into Tamagui's font config so no per-component `fontFamily` is set

### Spacing

`4 / 8 / 12 / 16 / 24 / 32 / 48` — Tamagui's `space` / `padding` props use these
tokens (`p="$3"` etc.).

### Assets

- `assets/sasai-logo.svg` — full lockup
- `assets/icon.png` — swoosh-only mark on a navy square
- `assets/splash.png` — full lockup centered; light variant on white, dark variant on
  `surfaceDk`

---

## 14. API client + data layer

### API client (`lib/api/client.ts`)

- Tiny typed `fetch` wrapper modeled on `mobile-simulator/lib/backend.ts`
- Injects headers: `Authorization: Bearer <session>`, `Idempotency-Key`,
  `X-Tenant-Id` (resolved at login from the session payload)
- Maps backend `{ error_code, message }` payloads to typed errors:
  `StepUpRequired`, `InvalidStepUpPin`, `InsufficientBalance`, `RecipientNotFound`,
  `Lockout`, `Network`, `Unknown`
- Never logs request bodies for `auth/*`, `payments/*`, `redemption/*` endpoints
  (anywhere PIN can appear)
- Per-domain modules: `api/auth.ts`, `api/wallet.ts`, `api/payments.ts`,
  `api/redemption.ts`, `api/catalog.ts`

### Data layer (`lib/query.ts`)

- Single TanStack Query client at the app root
- `qk` factory:
  - `qk.wallet()` — `GET /me/wallet`
  - `qk.catalog()` — `GET /catalog/me/summary`
  - `qk.featuredCampaign()` — featured campaign endpoint
  - `qk.redemption(id)` — `GET /redemption/{id}`
- Mutations invalidate the relevant keys on success (P2P / topup / redemption all
  invalidate `qk.wallet()`)
- `staleTime`: 30s on wallet; 5min on catalog

### Session & storage

- `expo-secure-store` (Keychain on iOS, EncryptedSharedPreferences on Android):
  - `session_token`
  - `last_phone_e164`
  - `biometric_session_token` (a token stashed only if user opts into biometrics,
    decrypted via Face ID / fingerprint on subsequent launches)
- `AsyncStorage`:
  - `theme_preference` — `system | light | dark` (override of `useColorScheme`)
  - `biometric_enabled` boolean

### Global error handling

- Root `ErrorBoundary` in `_layout.tsx` renders a friendly fallback (never a redbox)
- Network errors → toast with retry, not a full screen
- Lockout → full-screen "Try again in N minutes"
- Sentry wired but env-gated (off for `development`, on for `preview`)

---

## 15. Build & distribution

### EAS profiles (`eas.json`)

| Profile | Purpose | Backend |
|---|---|---|
| `development` | Dev client for fast iteration | `localhost:8000` |
| `preview` | Ad-hoc iOS (TestFlight) + Android APK for demos | Staging |
| `production` | Reserved for Phase 2 | Production (unused) |

### Commands

```bash
# Bootstrap (one time)
npx create-expo-app mobile -t default
cd mobile
npx expo install tamagui @tamagui/config @tamagui/lucide-icons \
  expo-router expo-secure-store expo-local-authentication \
  expo-font expo-blur expo-haptics expo-linear-gradient \
  @tanstack/react-query
npm i -D @types/react eslint prettier

# Local dev
npm start                       # Expo dev server
npm run ios                     # iOS simulator
npm run android                 # Android emulator

# Demo builds
eas build -p ios -e preview     # TestFlight artifact
eas build -p android -e preview # APK
```

### OTA updates

- `expo-updates` enabled for `preview` profile
- Hot-fix typos and polish without a new build: `eas update --branch preview`

---

## 16. Backend additions required

These are net-new or extended endpoints the mobile app depends on. Each must
follow `python-backend.md` (router/service split, idempotency, structured logs)
and `coding-guidelines.md` §3 (full automation tests).

| Change | Module | Notes |
|---|---|---|
| `POST /identity/auth/start` | `identity` | Body: `{ phone_e164 }`. Response: `{ status: "needs_otp" \| "needs_pin" }`. Identical response shape regardless of tenant to avoid cross-tenant existence leak. |
| `POST /payments/topup` | `payments` | Body: `{ amount, currency, demo_reference, pin? }`. Response: `{ ledger_entry_id, new_balance, earned_points }`. Internally calls `operator_adjustment` to credit the user's ZAR account. Tenant-scoped; idempotency-keyed; respects `step_up_policies` via `enforce_step_up`. Audit log entry tagged `source=mobile_demo_topup`. |
| `P2PResponse.earned_points` | `payments` | New optional field `earned_points: int \| null` set by the post-commit rules engine result. Avoids a polling round-trip for the rewards toast. |
| `GET /catalog/featured` (or query param on `/catalog/me/summary`) | `catalog` | Returns the single most relevant active campaign for the user. Used by the home featured-campaign card. Returns 200 + empty payload (not 404) when no campaign is active so the home page can collapse the slot. |
| `seed.py` enrichment | scripts | Pre-seed Alice + Bob with 4–5 historical P2Ps to populate the "Send again" carousel from the first launch. Pre-seed a small PTS balance + a couple of accrual entries so the rewards screen looks lived-in. |

All five changes are small and additive; none break existing admin-ui or
mobile-simulator behavior.

---

## 17. Compliance / fintech-rule alignment

Cross-checked against `compliance-fintech.md`, `python-backend.md`, `ledger-invariants.md`,
`coding-guidelines.md`, `observability.md`:

- **PII masking** — phone displayed in the app uses the same masking helpers
  (`mask_phone`) at the API boundary; activity rows show masked counterparty phones
- **No PIN in logs** — API client filters `pin` from any debug surface; backend
  rules already enforce this server-side
- **Idempotency** — every state-mutating call carries a client-generated key,
  reused across try-then-PIN retries
- **Append-only ledger** — top-up uses `operator_adjustment` against the system
  wallet (existing pattern); reversal flow is unchanged
- **External calls after commit** — n/a in the mobile app, but the new
  `/payments/topup` route inherits this from the existing payment orchestrator
- **Tenant isolation** — every API call is session-scoped; the session resolves the
  tenant on the server. The mobile client never sends `tenant_id` in a body.
- **Audit trail** — top-up generates audit-log entries (existing operator_adjustment
  path); P2P + redemption already do
- **Session inactivity** — 15-minute timeout for mobile (per NFR-0180); enforced by
  the session-expiry path that drops the token and routes to PIN screen
- **Frontend tests deferred** — per `coding-guidelines.md` §4. Backend tests for the
  new endpoints are required.

---

## 18. Open questions

None. All scope, contract, and UX questions resolved during brainstorm. The
implementation plan can proceed directly.
