/**
 * Tests for the pure base/derived catalog helpers.
 *
 * These carry the rules the Services screen is built on: how rows group under
 * their base, which bases may be derived from, and how an empty policy
 * selection is translated for an API that treats "empty" and "unrestricted"
 * as different things.
 */
import { describe, expect, it } from "vitest";

import type { Service } from "@/lib/api-types";
import {
  allowedOptions,
  derivableBases,
  groupServices,
  missingPrerequisites,
  policyValue,
} from "@/lib/service-catalog";

function makeService(overrides: Partial<Service> = {}): Service {
  return {
    id: "svc-1",
    tenant_id: "tenant-1",
    code: "p2p",
    display_name: "P2P Transfer",
    description: null,
    status: "active",
    kind: "base",
    base_service_code: null,
    derivable: true,
    readiness: null,
    allowed_user_types: null,
    allowed_channels: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const P2P = makeService();
const CASHOUT = makeService({ id: "svc-2", code: "cashout", display_name: "Cash Out" });
const DIASPORA = makeService({
  id: "svc-3",
  code: "p2p_diaspora",
  display_name: "Diaspora Transfer",
  kind: "derived",
  base_service_code: "p2p",
  derivable: false,
});
const ATM = makeService({
  id: "svc-4",
  code: "cashout_atm",
  display_name: "Cash Out (ATM)",
  kind: "derived",
  base_service_code: "cashout",
  derivable: false,
});

describe("groupServices", () => {
  it("Verify each base is followed by the services derived from it", () => {
    const ordered = groupServices([DIASPORA, CASHOUT, P2P, ATM]);

    expect(ordered.map((s) => s.code)).toEqual([
      "cashout",
      "cashout_atm",
      "p2p",
      "p2p_diaspora",
    ]);
  });

  it("Verify a derived service whose base is absent is still listed", () => {
    // The base can drop out of the list (soft-deleted, or a status filter).
    // The derived service still exists and still transacts, so hiding it
    // would be worse than showing it ungrouped at the end.
    const ordered = groupServices([DIASPORA, CASHOUT]);

    expect(ordered.map((s) => s.code)).toEqual(["cashout", "p2p_diaspora"]);
  });
});

describe("derivableBases", () => {
  it("Verify only server-marked derivable, active bases are offered", () => {
    const offered = derivableBases([
      P2P,
      DIASPORA, // a derivation cannot itself be derived from
      makeService({ id: "svc-5", code: "change_pin", derivable: false }),
      makeService({ id: "svc-6", code: "withdraw", status: "disabled" }),
    ]);

    expect(offered.map((s) => s.code)).toEqual(["p2p"]);
  });
});

describe("allowedOptions", () => {
  it("Verify an unrestricted base puts every value on the table", () => {
    expect(allowedOptions(null, ["consumer", "agent"])).toEqual([
      "consumer",
      "agent",
    ]);
  });

  it("Verify a restricted base limits the options to its own list", () => {
    // Narrowing-only: offering anything else would only earn a 422.
    expect(allowedOptions(["merchant"], ["consumer", "merchant"])).toEqual([
      "merchant",
    ]);
  });
});

describe("policyValue", () => {
  it("Verify a selection is sent as-is", () => {
    expect(policyValue(["consumer"], null)).toEqual(["consumer"]);
  });

  it("Verify empty on an unrestricted base means unrestricted, not empty", () => {
    // null and [] mean different things to the API: null inherits the base's
    // openness, [] would restrict to nobody.
    expect(policyValue([], null)).toBeNull();
  });

  it("Verify empty on a restricted base is never sent as unrestricted", () => {
    // null here would be WIDER than the base. The form blocks this state, so
    // the value is only a fallback — but it must not widen.
    expect(policyValue([], ["merchant"])).toEqual([]);
  });
});

describe("missingPrerequisites", () => {
  it("Verify a fully configured service reports nothing missing", () => {
    expect(
      missingPrerequisites({ pricing: true, limits: true, role: true }),
    ).toEqual([]);
  });

  it("Verify a brand-new service reports all three, in fix order", () => {
    expect(
      missingPrerequisites({ pricing: false, limits: false, role: false }),
    ).toEqual(["pricing", "limits", "role"]);
  });

  it("Verify unreported readiness is not treated as broken", () => {
    // null = the endpoint didn't compute it (create/patch responses), which is
    // not evidence of a missing config.
    expect(missingPrerequisites(null)).toEqual([]);
  });
});
