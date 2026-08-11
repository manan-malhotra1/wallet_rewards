/**
 * Unit tests for the bonus-multiplier lib helpers — lifecycle derivation
 * against the half-open window, scope labelling, and factor formatting.
 */
import { describe, expect, it } from "vitest";

import {
  deriveMultiplierStatus,
  describeMultiplierScope,
  formatMultiplierFactor,
  formatMultiplierWindow,
} from "@/lib/multiplier-status";

const NOW = new Date("2026-08-11T12:00:00Z");

describe("deriveMultiplierStatus — lifecycle from the validity window", () => {
  it("Verify an unbounded multiplier is always active", () => {
    expect(
      deriveMultiplierStatus({ valid_from: null, valid_until: null }, NOW),
    ).toBe("ACTIVE");
  });

  it("Verify a multiplier is scheduled before its start", () => {
    expect(
      deriveMultiplierStatus(
        { valid_from: "2026-09-01T00:00:00Z", valid_until: null },
        NOW,
      ),
    ).toBe("SCHEDULED");
  });

  it("Verify a multiplier is active inside its window", () => {
    expect(
      deriveMultiplierStatus(
        {
          valid_from: "2026-08-01T00:00:00Z",
          valid_until: "2026-09-01T00:00:00Z",
        },
        NOW,
      ),
    ).toBe("ACTIVE");
  });

  it("Verify a multiplier expires exactly at valid_until (half-open window)", () => {
    // [from, until): at the until instant the boost no longer applies.
    expect(
      deriveMultiplierStatus(
        {
          valid_from: "2026-08-01T00:00:00Z",
          valid_until: "2026-08-11T12:00:00Z",
        },
        NOW,
      ),
    ).toBe("EXPIRED");
  });

  it("Verify a multiplier is active exactly at valid_from (inclusive start)", () => {
    expect(
      deriveMultiplierStatus(
        { valid_from: "2026-08-11T12:00:00Z", valid_until: null },
        NOW,
      ),
    ).toBe("ACTIVE");
  });
});

describe("describeMultiplierScope — resolving scope to a label", () => {
  it("Verify a tenant-wide multiplier reads all points rules, all users", () => {
    expect(describeMultiplierScope(null, null)).toBe(
      "All points rules · All users",
    );
  });

  it("Verify a rule-scoped multiplier names the rule", () => {
    expect(describeMultiplierScope("First fund bonus", null)).toBe(
      "Rule: First fund bonus · All users",
    );
  });

  it("Verify a segment-only multiplier names the segment", () => {
    expect(describeMultiplierScope(null, "vip-users")).toBe(
      "All points rules · Segment: vip-users",
    );
  });

  it("Verify a rule+segment multiplier names both (intersection)", () => {
    expect(describeMultiplierScope("First fund bonus", "vip-users")).toBe(
      "Rule: First fund bonus · Segment: vip-users",
    );
  });
});

describe("formatMultiplierWindow — window label", () => {
  it("Verify no bounds reads as always active", () => {
    expect(formatMultiplierWindow(null, null)).toBe("Always active");
  });

  it("Verify an open-ended start reads as until-only", () => {
    expect(formatMultiplierWindow(null, "2026-09-01T00:00:00Z")).toMatch(/^Until /);
  });

  it("Verify an open-ended end reads as from-only", () => {
    expect(formatMultiplierWindow("2026-08-01T00:00:00Z", null)).toMatch(/^From /);
  });

  it("Verify a bounded window joins both ends", () => {
    expect(
      formatMultiplierWindow("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"),
    ).toContain("→");
  });
});

describe("formatMultiplierFactor — display formatting", () => {
  it("Verify integer factors drop trailing zeros", () => {
    expect(formatMultiplierFactor("2.00")).toBe("×2");
  });

  it("Verify fractional factors keep their precision", () => {
    expect(formatMultiplierFactor("1.50")).toBe("×1.5");
  });

  it("Verify a non-numeric factor falls back to the raw string", () => {
    expect(formatMultiplierFactor("abc")).toBe("×abc");
  });
});
