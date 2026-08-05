# 10 — Mobile App (Sasai Pay)

> **Document type:** Design (HOW). The consumer/agent app — how the Expo app is structured, how it resolves
> the backend, how it authenticates, and how the money + rewards surfaces are built.
> **Related:** [`.claude/skills/local-setup/SKILL.md`](../../.claude/skills/local-setup/SKILL.md) (running it,
> the connectivity matrix, dodging EAS build limits), [`mobile/DEV_CLIENT.md`](../../mobile/DEV_CLIENT.md)
> (dev-client vs EAS builds), [01-identity-auth-and-users](01-identity-auth-and-users.md) +
> [02-ledger-accounts-and-money-movement](02-ledger-accounts-and-money-movement.md) (the backend it drives).
> **README:** see the [design index](README.md) §10. Maps to **Pay-PRD Module 16 (User Mobile Surface)**.
> **Audience:** an engineer working on `mobile/`.

---

## 1. Architecture at a glance

**Stack:** Expo (SDK 54) + **expo-router** (file-based, headerless `Stack` — each route owns its chrome) +
**Tamagui** (theme/tokens) + a **Skia "clay" claymorphism** UI kit + **TanStack Query**. Fonts: Plus Jakarta
Sans. Brand: **Sasai Pay** (navy + teal). Tenant + user are implicit in the session token for authenticated
reads; **all money is multi-currency — never assume ZAR**.

**Provider tree** ([`mobile/app/_layout.tsx`](../../mobile/app/_layout.tsx)):
`GestureHandlerRootView → SafeAreaProvider → ThemeProvider → TamaguiProvider → PortalProvider →
QueryClientProvider → StatusBar → Stack`. The splash is held until fonts load; `ThemedApp` drives the theme
from `useThemePref()`.

**State / storage helpers** ([`mobile/lib/`](../../mobile/lib/)): `auth.ts` (`useSession()` →
`{loading, signedIn}`, `signOut()`), `bootstrap.ts` (one-shot cached `GET /events/sim-bootstrap` →
`{tenant_id, users}`; **dev/simulator only**, prod replacement pending), `storage.ts` (expo-secure-store keys:
`sasai.session_token`, `sasai.last_phone`, `sasai.registration_token`, `sasai.theme_pref`; `clearAll` keeps
theme), `query.ts` (QueryClient: retry 1, no refetch-on-focus, 30s stale; `qk` keys wallet/services/limits/
rewards), plus `theme.ts`, `colors.ts` (`useColors()` Skia-safe palette), `format.ts`, `masking.ts`.

---

## 2. Backend-URL resolution — `mobile/lib/env.ts`

The single most operationally important module. [`mobile/lib/env.ts`](../../mobile/lib/env.ts) resolves
`env.backendUrl` by **precedence**:

1. `process.env.EXPO_PUBLIC_BACKEND_URL` (from `.env.development`) —
2. `Constants.expoConfig?.extra?.backendUrl` (from `app.json`) —
3. hard fallback `http://localhost:8000` (so a forgotten env file doesn't break the simulator demo).

For **baked builds**, the URL comes from the **EAS "preview" remote env var**, not `app.json`. The simulator
uses `localhost:8000` (loopback + an iOS ATS localhost exception). The **connectivity matrix** below is
maintained in full by the [`local-setup` skill](../../.claude/skills/local-setup/SKILL.md) — reference it
rather than hard-coding a URL:

| Target | `EXPO_PUBLIC_BACKEND_URL` | Why |
|---|---|---|
| iOS simulator | `http://localhost:8000` | Simulator shares the Mac loopback. |
| Android emulator | `http://10.0.2.2:8000` | Emulator alias for the host loopback. |
| Physical phone (same LAN) | `http://<mac-LAN-IP>:8000` | Phone reaches the Mac by LAN address. |
| Physical phone (HTTPS) | `https://<tunnel-host>` | Tunnel when LAN/ATS blocks plain HTTP. |

---

## 3. The API client — `mobile/lib/api/`

Every backend call goes through one typed wrapper, [`mobile/lib/api/client.ts`](../../mobile/lib/api/client.ts):
`api<TResp, TBody>({ path, method, body?, withAuth?, idempotencyKey? })`. It builds
`${env.backendUrl}${path}`; sets `Accept`, `Content-Type`, `Idempotency-Key`, and (when `withAuth`)
`Authorization: Bearer <token>` from `getSessionToken()`; parses JSON (204 → `null`); and **never logs the
response body or the Authorization header** (they may carry session tokens). `newIdempotencyKey()` is
`crypto.randomUUID()` with a timestamp+random fallback.

**Typed errors** ([`errors.ts`](../../mobile/lib/api/errors.ts)): `ApiError(status, errorCode, message)` plus
subclasses `StepUpRequired` (401 `step_up_required`), `InvalidStepUpPin`, `SessionExpired`, `InvalidPin`,
`RateLimited` (429). `toTypedError()` maps status+code to the right subclass — this is what makes the uniform
step-up pattern (§6) and the lockout screens possible.

**Per-domain modules** (thin wrappers over `api()`):

| Module | Key calls |
|---|---|
| `auth.ts` | `authStart`, `otpSend` (optional `referral_code`), `otpVerify`, `pinSet` (204), `authPin`, `logout` |
| `wallet.ts` | `getMyWallet`, `getMyServices` + pure helpers `transactionTitle`/`transactionRef`/`activityCategory` |
| `payments.ts` | `sendP2P` (nested `recipient`, optional `pin`) |
| `cashin.ts` / `cashout.ts` | `cashIn` (nested `customer`) / `cashOut` (flat identifier) + failure-reason mappers |
| `airtime.ts` | `buyAirtime` + single follow-up `getAirtimeStatus` (branches on body `status`) |
| `rewards.ts` | `getRewards`, `markRewardsSeen` |
| `pricing.ts` / `limits.ts` | `quoteServiceFee(service, amount, currency)` / `getMyLimits` |

---

## 4. Provider tree & theming

The claymorphism look is a first-class kit, not styling sugar. `components/clay/` (Skia) has `recipe.ts` as
the single source of the look, rendered by `ClayShape` behind each primitive: `ClaySurface`/`ClayCard`,
`ClayInset`, `ClayButton` (navy-gradient primary / clay neutral, pressed + loading), `ClayKey`, `ClayPill`,
`ClayIconTile`. Brand chrome lives in `components/brand/` (`GradientHeader` navy hero with success/failed
variants, `SasaiPayLogo`, `StepIndicator`, `HeaderBack`). Theme preference is a single dark-mode switch bound
to `useThemePref()` (§7, Settings).

---

## 5. Auth flow (`mobile/app/auth/`)

Headerless stack; **self-registration is phone-first**. The four screens:

| Screen | Route | Does |
|---|---|---|
| `phone.tsx` | `/auth/phone` | Phone entry. "Create account" reveals an **optional referral-code field** (case-insensitive, upper-cased). Continue → `getTenantId()` (bootstrap) → `authStart()`; `needs_pin` → `/auth/pin`; new phone → `otpSend()` (threads referral code, catches 422 `invalid_referral_code` inline) → `/auth/otp`. |
| `otp.tsx` | `/auth/otp` | Six-box `OtpInput`, 30s resend, auto-submit, shake on error, dev-OTP hint. `otpVerify()` stores `registration_token` → `/auth/set-pin`. |
| `set-pin.tsx` | `/auth/set-pin` | Two-step create+confirm. On match: `pinSet(registrationToken)` (204) → clear reg token → `authPin()` for the session → `/home`. **The signup referral reward is paid backend-side at PIN-set** (verified, completed signup). |
| `pin.tsx` | `/auth/pin` | Returning-user PIN entry (masked phone, `PinInput` pips + keypad, shake on wrong PIN). `authPin()` → session → `/home`. `RateLimited` (429) → friendly lockout screen. |

Launch: `app/index.tsx` redirects via `useSession()` — cached token → `/home`, else `/auth/phone` (no
launch-time validation; trusts the cache until a 401).

---

## 6. Money surfaces & the uniform step-up pattern

**Home** ([`app/home.tsx`](../../mobile/app/home.tsx), Pay tab): navy `GradientHeader` (avatar/greeting,
tappable **points chip** → `/rewards`, bell), a **swipeable carousel of clay `BalanceCard`s — one per
`financial_wallet`, ordered by available balance desc** — with page dots and eye-toggle masking, and
**quick-action tiles driven by `/me/services`** (`p2p`→Send, `airtime_recharge`→Airtime, `cashout`→Cash out,
`cash_in`→Cash in; the active card's currency threads into each route). Recent activity = last 3 for the
active currency + PTS. Reads `getMyWallet`, `getMyServices`, `getRewards`.

The three governed money flows (`p2p/`, `cashin/`, `cashout/`) share a **uniform step-up pattern** — the
client optimistically fires *without* a PIN and only prompts when the backend demands it:

```
amount screen → api call WITHOUT pin
  → 200  → /success
  → 401 step_up_required (StepUpRequired) → /…/pin screen
        → replay the SAME call WITH pin AND the SAME idempotency key
              → 200 → /success   |   InvalidStepUpPin → shake+clear+retry   |   else → /failed
  → other error → /failed
```

Reusing the idempotency key is safe because **both rejections happen pre-ledger**, so the replay can never
double-post (see [02-ledger](02-ledger-accounts-and-money-movement.md) idempotency). Each flow also shows a
**live fee preview** via `quoteServiceFee(...)` and guards overdraft on `amount + fee`.

| Flow | Dir | Step 1 | Step 2 | Step-up? |
|---|---|---|---|---|
| P2P send | `app/p2p/` | recipient (probe via `authStart`) | amount + fee preview → `sendP2P` | ✅ `/p2p/pin` |
| Cash-in (agent funds customer) | `app/cashin/` | customer phone | amount → `cashIn` | ✅ `/cashin/pin` |
| Cash-out (subscriber → agent) | `app/cashout/` | agent phone (backend validates) | amount → `cashOut` | ✅ `/cashout/pin` |
| Airtime | `app/airtime/index.tsx` | single self-contained screen | `buyAirtime` + one delayed `getAirtimeStatus` poll | ❌ **no step-up** |

Airtime is the exception: a single screen renders success/processing/error **inline** (no separate route); its
idempotency key is held in a ref, reset on input change, reused on retry.

> **Accuracy flag.** `p2p/success.tsx` hardcodes an "R" currency symbol / "Fee R 0.00" though the flow is
> multi-currency; and `lib/format.ts` and `lib/masking.ts` carry two slightly different `maskPhone`
> implementations. Both are known cosmetic debts.

---

## 7. Rewards, history, limits & settings

**Rewards** ([`app/rewards/index.tsx`](../../mobile/app/rewards/index.tsx)): empty state when
`enabled === false`; otherwise three sections — a **refer-a-friend card** (shown only when `referral_code` is
present; native OS `Share` sheet), **Progress** (`catalog` rules as `CatalogCard`s with teal progress bars +
earned/in-progress/locked pills), and **Recent** earned rewards. Reads `getRewards`.

The **celebration overlay** fires on `/home`, not here: the first *unseen* earned reward pops
`components/rewards/RewardCelebration.tsx` (full-screen dimmed `Modal`, spring clay card, "You earned … !");
dismiss → `markRewardsSeen()`. This is the visible end of the `both`-mode reward outbox pipeline
([05-rewards](05-rewards-rules-and-referral.md)) — rewards land server-side, and the app surfaces the first
unseen one.

**Transactions** (`app/transactions.tsx`): day-grouped `ActivityRow`s with fee/tax/commission meta,
interactive filter chips (All/Sent/Received/Bills — Bills is a v0 placeholder), currency-scope chips when >1
wallet, and a **single-currency money-in/out summary strip (never summed across currencies)**. **Limits**
(`app/limits/index.tsx`): per-currency wallet blocks, Send + Receive × Daily/Weekly/Monthly rows
(consumed vs cap, "No limit" when null) from `getMyLimits`; again money is never summed across currencies.
**Settings** (`app/settings/index.tsx`): a single dark-mode `Switch` (beta) bound to `useThemePref().setPref`;
full profile/security is a side-drawer placeholder.

**Per-currency discipline** is a hard rule across every surface: the home carousel is one card per wallet, the
transactions summary and limits are per-currency, and no screen sums money across currencies — matching the
backend analytics contract in [11-cross-cutting](11-cross-cutting-observability-compliance-security.md).

---

## 8. Builds & the repo rule

Two build paths: an **Expo dev client** (fast iteration, JS reloaded over the dev server) and **EAS builds**
(a baked `.apk`/`.ipa` for phones without a dev server). Which to use, and how to work around EAS free-tier
limits, is documented in [`mobile/DEV_CLIENT.md`](../../mobile/DEV_CLIENT.md) and the
[`local-setup` skill](../../.claude/skills/local-setup/SKILL.md).

> **Repo rule (per project memory): never trigger an EAS/mobile build unasked.** Commit + typecheck, then
> *offer* the build. Baked builds read their backend URL from the EAS "preview" env var (§2), so a build
> targets whatever that var points at.
