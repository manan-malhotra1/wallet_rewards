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
 *
 * Session expiry: if a wallet read 401s, we drop the cache and
 * re-login transparently before retrying once.
 */
import "server-only";

import { config, type UserKey } from "@/lib/config";
import { signEventBody } from "@/lib/hmac";

interface Bootstrap {
  tenant_id: string;
  tenant_name: string;
  users: Record<string, string>;
}

let bootstrapPromise: Promise<Bootstrap> | null = null;
const sessionCache = new Map<string, string>();

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
  transaction_type: string;
  status: string;
  amount: string;
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

async function _login(phone: string, pin: string): Promise<string> {
  const cached = sessionCache.get(phone);
  if (cached) return cached;
  const { tenant_id } = await getBootstrap();
  const res = await fetch(`${config.backendUrl}/api/v1/identity/auth/pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tenant_id, phone, pin }),
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(
      `PIN login failed for ${phone}: ${res.status} ${await res.text()}`,
    );
  }
  const payload: { session_token: string } = await res.json();
  sessionCache.set(phone, payload.session_token);
  return payload.session_token;
}

async function loginUser(user: UserKey): Promise<string> {
  const u = config.users[user];
  return _login(u.phone, u.pin);
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
