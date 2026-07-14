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
  users: {
    alice: {
      label: "Alice",
      phone: required("SASAI_ALICE_PHONE"),
      pin: required("SASAI_ALICE_PIN"),
    },
    bob: {
      label: "Bob",
      phone: required("SASAI_BOB_PHONE"),
      pin: required("SASAI_BOB_PIN"),
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
} as const;

export type UserKey = "alice" | "bob";

export function otherUser(u: UserKey): UserKey {
  return u === "alice" ? "bob" : "alice";
}
