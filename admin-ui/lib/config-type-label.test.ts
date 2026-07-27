/**
 * Tests for config-type label mapping — every ConfigType must resolve to a
 * friendly label so a raw code never leaks into a maker-checker surface.
 */
import { describe, expect, it } from "vitest";

import { configTypeLabel } from "@/lib/config-type-label";
import type { ConfigType } from "@/lib/api-types";

/** The full set of config types the UI must label. */
const ALL_CONFIG_TYPES: ConfigType[] = [
  "pricing",
  "limit",
  "wallet_limit",
  "commission",
  "tax",
  "step_up",
];

describe("Configuration type names", () => {
  it.each(ALL_CONFIG_TYPES)(
    "Every configuration type shows a readable name, not a raw code (%s)",
    (type) => {
      const label = configTypeLabel(type);
      expect(label).toBeTruthy();
      expect(label).not.toBe(type);
      expect(label).not.toContain("_");
    },
  );

  it("Step-up policies are labelled 'Step-up PIN policy'", () => {
    expect(configTypeLabel("step_up")).toBe("Step-up PIN policy");
  });

  it("Pricing configurations are labelled 'Service charge'", () => {
    expect(configTypeLabel("pricing")).toBe("Service charge");
  });
});
