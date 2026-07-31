import { describe, expect, it } from "vitest";

import { percentDelta, formatDelta } from "./analytics-format";

describe("analytics-format", () => {
  it("computes percent change vs previous", () => {
    expect(percentDelta("120", "100")).toBeCloseTo(20);
    expect(percentDelta("80", "100")).toBeCloseTo(-20);
  });

  it("treats growth from zero as null (no baseline)", () => {
    expect(percentDelta("50", "0")).toBeNull();
  });

  it("formats a delta with direction and sign", () => {
    expect(formatDelta(20)).toEqual({ label: "+20.0%", direction: "up" });
    expect(formatDelta(-5.5)).toEqual({ label: "-5.5%", direction: "down" });
    expect(formatDelta(null)).toEqual({ label: "—", direction: "flat" });
  });
});
