/**
 * Server-only env config for the mobile-simulator.
 *
 * All values come from .env.local — see .env.local.example for the
 * defaults. The simulator is a dev tool; production deployment of this
 * app is not supported.
 */
import "server-only";

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `Missing env var ${name}. Copy .env.local.example to .env.local.`,
    );
  }
  return value;
}

export const config = {
  backendUrl: process.env.SASAI_BACKEND_URL ?? "http://localhost:8000",
  tenantName: process.env.SASAI_TENANT_NAME ?? "Sasai-ZA",
  // Each user has a required `phone` (the seeded default) and an OPTIONAL `pin`.
  // The PIN here is only a convenience hint of the seeded default — operators log
  // each user in through the UI, and the entered PIN lives in the runtime
  // credential store (lib/backend.ts), NOT here. Nothing authenticates with this
  // field; it is safe to leave unset.
  users: {
    alice: {
      label: "Alice",
      phone: required("SASAI_ALICE_PHONE"),
      pin: process.env.SASAI_ALICE_PIN,
    },
    bob: {
      label: "Bob",
      phone: required("SASAI_BOB_PHONE"),
      pin: process.env.SASAI_BOB_PIN,
    },
    // Agent + merchant default to the seeded phones so existing .env.local files
    // keep working without edits (scripts/seed.py seeds both).
    agent: {
      label: "Grace (Agent)",
      phone: process.env.SASAI_AGENT_PHONE ?? "+27825558001",
      pin: process.env.SASAI_AGENT_PIN,
    },
    merchant: {
      label: "Airtime Merchant",
      phone: process.env.SASAI_MERCHANT_PHONE ?? "+27825559001",
      pin: process.env.SASAI_MERCHANT_PIN,
    },
  },
  eventSource: {
    key: process.env.EVENT_SOURCE_KEY ?? "sasai-bank",
    secret: process.env.EVENT_SOURCE_SECRET ?? "",
  },
  // Dev-only: the seeded airtime merchant's callback secret. Lets the UI sign a
  // simulated provider callback to finalise a PENDING recharge (the bundled
  // SimulatorProvider never calls back on its own). Matches scripts/seed.py.
  airtimeCallbackSecret:
    process.env.AIRTIME_CALLBACK_SECRET ??
    "dev-airtime-callback-secret-do-not-use-in-prod",
  // Dev-only: the seeded partner API key used to call the external fund /
  // withdraw endpoints. These endpoints use API-key + HMAC auth (X-Sasai-Api-Key
  // + X-Sasai-Signature) rather than the user PIN/bearer flow; the tenant is
  // derived from the key. Defaults match the dev key provisioned by `make seed`.
  externalApi: {
    keyId: process.env.SASAI_API_KEY_ID ?? "sim-dev-key",
    secret:
      process.env.SASAI_API_KEY_SECRET ??
      "dev-external-api-secret-do-not-use-in-prod",
  },
} as const;

export type UserKey = "alice" | "bob" | "agent" | "merchant";

/** The P2P counterparty for alice/bob (the two consumer wallets). */
export function otherUser(u: UserKey): UserKey {
  return u === "alice" ? "bob" : "alice";
}
