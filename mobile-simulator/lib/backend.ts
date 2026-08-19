/**
 * Server-only wrappers around the Sasai backend API.
 *
 * No browser ever sees PINs or session tokens — every backend call
 * goes through these helpers from a server component or server action.
 *
 * Module-level caches:
 *   - bootstrap (tenant_id + user_id-by-phone): fetched once from
 *     /api/v1/events/sim-bootstrap, reused for the process lifetime.
 *   - session tokens: cached per-phone after the first PIN login.
 *   - credential store: the PIN each user logged in with, keyed by phone.
 *     Populated by `login`, read by `loginUser` (so the money/step-up paths
 *     can silently re-login after a session expiry), cleared by `logout`.
 *
 * There is NO hardcoded default PIN: an operator must log a user in through
 * the UI first. Both maps are module-level, so a server restart logs everyone
 * out — acceptable for a dev tool.
 *
 * Session expiry: if a wallet read 401s, we drop the token cache and
 * re-login transparently (using the stored PIN) before retrying once.
 */
import "server-only";

import { config, type UserKey } from "@/lib/config";
import { signEventBody, signExternalBody } from "@/lib/hmac";

interface Bootstrap {
  tenant_id: string;
  tenant_name: string;
  users: Record<string, string>;
}

let bootstrapPromise: Promise<Bootstrap> | null = null;
const sessionCache = new Map<string, string>();
const credentialStore = new Map<string, string>();

/**
 * Thrown when a money/step-up path needs a user's session but the operator has
 * not logged that user in yet (no stored PIN / token). Carries a friendly
 * message the server action surfaces verbatim.
 */
export class NotLoggedInError extends Error {
  constructor(public readonly user: UserKey) {
    super(
      `${config.users[user].label} is not logged in — enter their PIN and log in first.`,
    );
    this.name = "NotLoggedInError";
  }
}

/** Whether a user currently has a stored PIN (i.e. the operator logged them in). */
export function isLoggedIn(user: UserKey): boolean {
  return credentialStore.has(config.users[user].phone);
}

/** Typed outcome of a PIN login attempt, mapped from the backend's HTTP status. */
export type LoginOutcome =
  | { ok: true }
  | {
      ok: false;
      kind: "invalid_credentials" | "account_locked" | "other";
      message: string;
    };

async function getBootstrap(): Promise<Bootstrap> {
  if (!bootstrapPromise) {
    bootstrapPromise = (async () => {
      const res = await fetch(
        `${config.backendUrl}/api/v1/events/sim-bootstrap`,
        { cache: "no-store" },
      );
      if (!res.ok) {
        throw new Error(
          `Sim bootstrap failed (${res.status}). Is the backend running ` +
            "with SIMULATOR_DEV_MODE=true and has `make seed` been run?",
        );
      }
      return res.json();
    })();
  }
  return bootstrapPromise;
}

interface WalletAccount {
  id: string;
  account_type: string;
  currency: string;
  status: string;
  balance: string;
  reserved_balance: string;
  available_balance: string;
}

export interface WalletTransaction {
  id: string;
  // Customer-facing reference `S_<datetime><seq>` (null only for un-backfilled legacy rows).
  reference: string | null;
  transaction_type: string;
  // The BASE flow — equals `transaction_type` unless made on a derived service.
  base_transaction_type: string;
  status: string;
  amount: string;
  // Charge breakdown (decimal strings; "0.000000" when none) — shown per row.
  fee_amount: string;
  commission_amount: string;
  tax_amount: string;
  currency: string;
  created_at: string;
}

export interface Wallet {
  user_id: string;
  tenant_id: string;
  first_name: string | null;
  accounts: WalletAccount[];
  recent_transactions: WalletTransaction[];
}

/**
 * POST phone+PIN to the backend auth endpoint.
 *
 * Returns the raw status + parsed token so callers can distinguish 401
 * (invalid credentials) from 423 (account locked). Does NOT touch any cache.
 */
async function postPinLogin(
  phone: string,
  pin: string,
): Promise<{ status: number; token: string | null; body: string }> {
  const { tenant_id } = await getBootstrap();
  const res = await fetch(`${config.backendUrl}/api/v1/identity/auth/pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tenant_id, phone, pin }),
    cache: "no-store",
  });
  const body = await res.text();
  let token: string | null = null;
  if (res.ok) {
    try {
      token = (JSON.parse(body) as { session_token: string }).session_token;
    } catch {
      token = null;
    }
  }
  return { status: res.status, token, body };
}

/**
 * Return a valid session token for `phone`, logging in with `pin` if none is
 * cached. Used on the money/step-up paths where the PIN comes from the
 * credential store. Throws a plain Error if the stored PIN is somehow rejected.
 */
async function _login(phone: string, pin: string): Promise<string> {
  const cached = sessionCache.get(phone);
  if (cached) return cached;
  const res = await postPinLogin(phone, pin);
  if (!res.token) {
    throw new Error(`PIN login failed for ${phone}: ${res.status} ${res.body}`);
  }
  sessionCache.set(phone, res.token);
  return res.token;
}

/**
 * Log a user in with an operator-entered PIN.
 *
 * On success, stores the PIN in the credential store and caches the token so
 * the money/step-up paths work without re-prompting. Returns a typed outcome;
 * a wrong PIN (401) or lockout (423) is a normal result, not an exception.
 */
export async function login(user: UserKey, pin: string): Promise<LoginOutcome> {
  const phone = config.users[user].phone;
  const res = await postPinLogin(phone, pin);
  if (res.token) {
    credentialStore.set(phone, pin);
    sessionCache.set(phone, res.token);
    return { ok: true };
  }
  if (res.status === 401) {
    return {
      ok: false,
      kind: "invalid_credentials",
      message: "Incorrect PIN.",
    };
  }
  if (res.status === 423) {
    return {
      ok: false,
      kind: "account_locked",
      message: "Account locked — too many failed attempts. Try again later.",
    };
  }
  return { ok: false, kind: "other", message: `${res.status}: ${res.body}` };
}

/**
 * Log a user out: drop their cached token + stored PIN, and best-effort
 * invalidate the session server-side. Idempotent — logging out an
 * already-logged-out user is a no-op.
 */
export async function logout(user: UserKey): Promise<void> {
  const phone = config.users[user].phone;
  const token = sessionCache.get(phone);
  sessionCache.delete(phone);
  credentialStore.delete(phone);
  if (!token) return;
  // Best-effort backend logout; a dev tool tolerates this failing.
  try {
    await fetch(`${config.backendUrl}/api/v1/identity/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    // Local caches are already cleared — the operator is logged out regardless.
  }
}

/**
 * Return a session token for `user`, sourcing the PIN from the credential store.
 * Raises NotLoggedInError if the operator has not logged this user in yet —
 * there is no hardcoded default PIN to fall back on.
 */
async function loginUser(user: UserKey): Promise<string> {
  const phone = config.users[user].phone;
  const pin = credentialStore.get(phone);
  if (!pin) throw new NotLoggedInError(user);
  return _login(phone, pin);
}

async function userIdFor(user: UserKey): Promise<string> {
  const { users } = await getBootstrap();
  const phone = config.users[user].phone;
  const id = users[phone];
  if (!id) {
    throw new Error(
      `Seeded user not found in backend bootstrap: ${phone}. ` +
        "Re-run `make seed`.",
    );
  }
  return id;
}

export async function getMyWallet(user: UserKey): Promise<Wallet> {
  async function once(): Promise<Response> {
    const token = await loginUser(user);
    return fetch(`${config.backendUrl}/api/v1/identity/me/wallet`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  }
  let res = await once();
  if (res.status === 401) {
    // Session expired — drop the cache and try once more.
    sessionCache.delete(config.users[user].phone);
    res = await once();
  }
  if (!res.ok) {
    throw new Error(`wallet fetch failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export async function sendP2P(
  sender: UserKey,
  recipient: UserKey,
  amount: string,
  pin?: string,
): Promise<{ ok: boolean; status: number; body: string }> {
  const recipientPhone = config.users[recipient].phone;
  // Fresh Idempotency-Key per attempt — backend dedups by (tenant, key)
  // so the simulator must NOT reuse the same key on retry (would return
  // the original response without re-running auth).
  const newKey = () =>
    `sim-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  // `pin` is included on the retry that follows a `step_up_required` 401.
  const body = (): string =>
    JSON.stringify({
      recipient: { identifier_type: "phone", identifier_value: recipientPhone },
      amount,
      currency: "ZAR",
      ...(pin ? { pin } : {}),
    });

  async function once(): Promise<Response> {
    const token = await loginUser(sender);
    return fetch(`${config.backendUrl}/api/v1/payments/p2p`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": newKey(),
      },
      body: body(),
      cache: "no-store",
    });
  }

  let res = await once();
  // 401 here means an expired session — drop the cached token + retry
  // ONCE. A genuine step-up failure also returns 401 but with a
  // different error_code; we let it surface to the caller.
  if (res.status === 401) {
    const text = await res.text();
    if (!text.includes("step_up_required") && !text.includes("invalid_step_up_pin")) {
      sessionCache.delete(config.users[sender].phone);
      res = await once();
      return { ok: res.ok, status: res.status, body: await res.text() };
    }
    return { ok: false, status: 401, body: text };
  }
  return { ok: res.ok, status: res.status, body: await res.text() };
}

export async function cashIn(
  agent: UserKey,
  customer: UserKey,
  amount: string,
  pin?: string,
): Promise<{ ok: boolean; status: number; body: string }> {
  // Agent funds the customer's wallet from the agent's e-float, earning a
  // commission. Mirrors sendP2P's step-up + expired-session retry handling.
  const customerPhone = config.users[customer].phone;
  const newKey = () =>
    `sim-cashin-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const body = (): string =>
    JSON.stringify({
      customer: { identifier_type: "phone", identifier_value: customerPhone },
      amount,
      currency: "ZAR",
      ...(pin ? { pin } : {}),
    });

  async function once(): Promise<Response> {
    const token = await loginUser(agent);
    return fetch(`${config.backendUrl}/api/v1/cashin`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": newKey(),
      },
      body: body(),
      cache: "no-store",
    });
  }

  let res = await once();
  if (res.status === 401) {
    const text = await res.text();
    if (!text.includes("step_up_required") && !text.includes("invalid_step_up_pin")) {
      sessionCache.delete(config.users[agent].phone);
      res = await once();
      return { ok: res.ok, status: res.status, body: await res.text() };
    }
    return { ok: false, status: 401, body: text };
  }
  return { ok: res.ok, status: res.status, body: await res.text() };
}

export async function cashOut(
  subscriber: UserKey,
  agentPhone: string,
  amount: string,
  pin?: string,
): Promise<{ ok: boolean; status: number; body: string }> {
  // Subscriber sends money to the agent (cash-out): the subscriber is debited
  // (amount + fee), the agent credited. Uses the subscriber's PIN/bearer flow —
  // same step-up + expired-session retry handling as sendP2P/cashIn. The body is
  // flat (identifier_type/identifier_value at top level), unlike cashIn's nested
  // `customer` object.
  const newKey = () =>
    `sim-cashout-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const body = (): string =>
    JSON.stringify({
      identifier_type: "phone",
      identifier_value: agentPhone,
      amount,
      currency: "ZAR",
      ...(pin ? { pin } : {}),
    });

  async function once(): Promise<Response> {
    const token = await loginUser(subscriber);
    return fetch(`${config.backendUrl}/api/v1/cashout`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": newKey(),
      },
      body: body(),
      cache: "no-store",
    });
  }

  let res = await once();
  if (res.status === 401) {
    const text = await res.text();
    if (!text.includes("step_up_required") && !text.includes("invalid_step_up_pin")) {
      sessionCache.delete(config.users[subscriber].phone);
      res = await once();
      return { ok: res.ok, status: res.status, body: await res.text() };
    }
    return { ok: false, status: 401, body: text };
  }
  return { ok: res.ok, status: res.status, body: await res.text() };
}

export async function changePin(
  user: UserKey,
  currentPin: string,
  newPin: string,
  currency = "ZAR",
): Promise<{ ok: boolean; status: number; body: string }> {
  // Charged self-service: the user changes their own PIN via their bearer
  // session, with `current_pin` gating the change server-side. Unlike
  // sendP2P/cashOut we must NOT blindly retry a 401 — a wrong current PIN is a
  // 401 (`invalid_credentials`) that counts toward lockout, so re-sending it
  // would burn another attempt. Only an expired/unknown session (401
  // `invalid_session`) is safe to retry after dropping the cached token.
  // Fresh Idempotency-Key per attempt (backend dedups by (tenant, key)).
  const newKey = () =>
    `sim-pinchg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const body = JSON.stringify({
    current_pin: currentPin,
    new_pin: newPin,
    currency,
  });

  async function once(): Promise<Response> {
    const token = await loginUser(user);
    return fetch(`${config.backendUrl}/api/v1/pin/change`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": newKey(),
      },
      body,
      cache: "no-store",
    });
  }

  let res = await once();
  if (res.status === 401) {
    const text = await res.text();
    if (text.includes("invalid_session")) {
      // Expired session only — safe to drop the cache and retry once.
      sessionCache.delete(config.users[user].phone);
      res = await once();
      return { ok: res.ok, status: res.status, body: await res.text() };
    }
    // Wrong current PIN / no PIN set — surface without retrying.
    return { ok: false, status: 401, body: text };
  }
  return { ok: res.ok, status: res.status, body: await res.text() };
}

export interface AirtimeResult {
  ok: boolean;
  status: number;
  body: string;
}

export async function buyAirtime(
  buyer: UserKey,
  msisdn: string,
  amount: string,
): Promise<AirtimeResult> {
  // Fresh Idempotency-Key per attempt (backend dedups by (tenant, key)).
  const newKey = () =>
    `sim-airtime-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const body = JSON.stringify({
    msisdn,
    network: "MTN",
    amount,
    currency: "ZAR",
  });

  async function once(): Promise<Response> {
    const token = await loginUser(buyer);
    return fetch(`${config.backendUrl}/api/v1/airtime/recharge`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": newKey(),
      },
      body,
      cache: "no-store",
    });
  }

  let res = await once();
  if (res.status === 401) {
    // Expired session — drop the cached token and retry once.
    sessionCache.delete(config.users[buyer].phone);
    res = await once();
  }
  return { ok: res.ok, status: res.status, body: await res.text() };
}

export async function simulateAirtimeCallback(
  rechargeId: string,
  outcome: "completed" | "failed",
): Promise<AirtimeResult> {
  // The bundled SimulatorProvider never fires a callback itself, so the UI can
  // send one to finalise a PENDING recharge. Signed with the seeded merchant's
  // dev callback secret (HMAC over `{ts}.{body}`); the HMAC IS the auth — no
  // Authorization header.
  const body = JSON.stringify(
    outcome === "completed"
      ? { outcome, provider_reference: `SIM-CB-${Date.now()}` }
      : { outcome, reason: "simulated_provider_failure" },
  );
  const signature = signEventBody(body, config.airtimeCallbackSecret);
  const res = await fetch(
    `${config.backendUrl}/api/v1/airtime/${rechargeId}/callback`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Sasai-Signature": signature,
      },
      body,
      cache: "no-store",
    },
  );
  return { ok: res.ok, status: res.status, body: await res.text() };
}

export interface ExternalResult {
  ok: boolean;
  status: number;
  body: string;
}

/**
 * POST a body to a partner external-API path with API-key + HMAC auth.
 *
 * These endpoints do NOT use the user PIN/bearer flow: the tenant is derived
 * from the API key, so the body never carries tenant_id. Auth is the pair of
 * headers `X-Sasai-Api-Key` (the key id) and `X-Sasai-Signature` (HMAC-SHA256
 * over `{ts}.{rawBody}` with the key's secret). A 422 `service_not_configured`
 * / `pricing_config_missing` is a valid, expected outcome (fail-closed) until a
 * fund/withdraw pricing+limits config exists — the caller surfaces it as such.
 *
 * Args:
 *   path: external path under the API root (e.g. "external/fund").
 *   payload: request body object; serialised verbatim as the signed raw body.
 *
 * Returns:
 *   `{ ok, status, body }` — body is the raw response text (JSON string).
 */
async function postExternal(
  path: string,
  payload: Record<string, unknown>,
): Promise<ExternalResult> {
  // Serialise once: the exact bytes sent MUST be the bytes signed, so we sign
  // this string and pass the same string as the request body.
  const rawBody = JSON.stringify(payload);
  const signature = signExternalBody(rawBody, config.externalApi.secret);
  const res = await fetch(`${config.backendUrl}/api/v1/${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Sasai-Api-Key": config.externalApi.keyId,
      "X-Sasai-Signature": signature,
      // State-mutating endpoints require an idempotency key (invariant #2).
      // A fresh key per call; the HMAC covers the body only, so this header
      // is outside the signed bytes and safe to add here.
      "Idempotency-Key": `sim-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    },
    body: rawBody,
    cache: "no-store",
  });
  return { ok: res.ok, status: res.status, body: await res.text() };
}

export async function externalFund(
  targetPhone: string,
  amount: string,
  currency: string,
  reason?: string,
): Promise<ExternalResult> {
  // Credits the target user's financial_wallet. Identifier resolves an existing
  // simulator user by phone (the type the seeded users are keyed on).
  return postExternal("external/fund", {
    identifier_type: "phone",
    identifier_value: targetPhone,
    amount,
    currency,
    ...(reason ? { reason } : {}),
  });
}

export async function externalWithdraw(
  targetPhone: string,
  currency: string,
  opts: { amount?: string; withdrawAll?: boolean; reason?: string },
): Promise<ExternalResult> {
  // Debits the target user's financial_wallet. The backend requires EXACTLY ONE
  // of `amount` or `withdraw_all: true`; the UI enforces that, and here we only
  // send whichever was chosen so we never violate the mutual-exclusion.
  return postExternal("external/withdraw", {
    identifier_type: "phone",
    identifier_value: targetPhone,
    currency,
    ...(opts.withdrawAll ? { withdraw_all: true } : { amount: opts.amount }),
    ...(opts.reason ? { reason: opts.reason } : {}),
  });
}

export async function merchantCashin(
  targetPhone: string,
  amount: string,
  currency: string,
  reason?: string,
): Promise<ExternalResult> {
  // Debits the merchant's own wallet (resolved from the API key, which is bound
  // to a funded merchant) and credits the CONSUMER recipient. The consumer is
  // targeted by phone — the identifier type the seeded users are keyed on. A
  // fail-closed 422 (service_not_configured), a 409 (insufficient_funds, merchant
  // underfunded), or a 403 (not_a_merchant_key) are all valid, expected outcomes.
  return postExternal("external/merchant-cashin", {
    identifier_type: "phone",
    identifier_value: targetPhone,
    amount,
    currency,
    ...(reason ? { reason } : {}),
  });
}

/** One partner-supplied identifier for external user creation. */
export interface ExternalIdentifier {
  identifier_type: "phone" | "email" | "account_number" | "card_number";
  identifier_value: string;
}

export async function externalCreateUser(
  identifiers: ExternalIdentifier[],
): Promise<ExternalResult> {
  // Creates a user from partner-supplied identifiers (no `verified` flag — a
  // partner can't assert verification). The identifier is the idempotency key:
  // the backend returns 201 for a new user and 200 (not 409) if an identifier
  // already maps to an existing one. The caller distinguishes the two by status.
  return postExternal("external/users", { identifiers });
}

interface EventInput {
  user: UserKey;
  transactionType: string;
  amount: string;
}

async function buildEventBody(input: EventInput): Promise<string> {
  const boot = await getBootstrap();
  const userId = await userIdFor(input.user);
  return JSON.stringify({
    event_id: `sim-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    tenant_id: boot.tenant_id,
    user_id: userId,
    source_key: config.eventSource.key,
    transaction_type: input.transactionType,
    amount: input.amount,
    currency: "ZAR",
    timestamp: new Date().toISOString(),
    raw: {},
  });
}

export async function fireEventHttp(
  input: EventInput,
): Promise<{ ok: boolean; status: number; body: string }> {
  const body = await buildEventBody(input);
  const signature = signEventBody(body, config.eventSource.secret);
  const res = await fetch(`${config.backendUrl}/api/v1/events/sim-ingest`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Sasai-Signature": signature,
    },
    body,
    cache: "no-store",
  });
  return { ok: res.ok, status: res.status, body: await res.text() };
}

export async function fireEventKafka(
  input: EventInput,
): Promise<{ ok: boolean; status: number; body: string }> {
  const body = await buildEventBody(input);
  const res = await fetch(
    `${config.backendUrl}/api/v1/events/sim-kafka-produce`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      cache: "no-store",
    },
  );
  return { ok: res.ok, status: res.status, body: await res.text() };
}
