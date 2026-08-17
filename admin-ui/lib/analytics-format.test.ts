import { describe, expect, it } from "vitest";

import {
  abbreviateNumber,
  formatBucketLabel,
  formatCount,
  formatDelta,
  percentDelta,
  rangeLabel,
  sharePercent,
} from "./analytics-format";

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

describe("formatCount", () => {
  it("Verify figures are grouped and rounded to whole units", () => {
    expect(formatCount(1234567.4)).toBe("1,234,567");
  });

  it("Verify a non-numeric input renders a dash rather than NaN", () => {
    expect(formatCount(Number("abc"))).toBe("—");
  });
});

describe("abbreviateNumber", () => {
  it.each([
    [842, "842"],
    [1240, "1.2k"],
    [12400, "12k"],
    [124000, "124k"],
    [3120000, "3.1M"],
    [1200000000, "1.2B"],
  ])("Verify %s abbreviates to %s", (input, expected) => {
    expect(abbreviateNumber(input)).toBe(expected);
  });

  it("Verify the decimal is dropped once the mantissa reaches two digits", () => {
    // Keeps a column of axis labels to a consistent width.
    expect(abbreviateNumber(2000)).toBe("2k");
    expect(abbreviateNumber(9900)).toBe("9.9k");
  });

  it("Verify negative figures keep their sign", () => {
    expect(abbreviateNumber(-12400)).toBe("-12k");
  });
});

describe("sharePercent", () => {
  it("Verify a share is reported to one decimal", () => {
    expect(sharePercent(25, 200)).toBe("12.5%");
  });

  it("Verify a zero total reads as 0.0% instead of dividing by zero", () => {
    expect(sharePercent(5, 0)).toBe("0.0%");
  });
});

describe("formatBucketLabel", () => {
  it("Verify a date bucket is parsed textually so the label cannot shift a day by timezone", () => {
    // new Date("2026-08-17") is UTC midnight — west of Greenwich that renders
    // as the 16th. Parsing the string directly keeps the label as written.
    expect(formatBucketLabel("2026-08-17", "day")).toBe("8/17");
  });

  it("Verify a 24h range labels by hour", () => {
    expect(formatBucketLabel("2026-08-17T14:00:00Z", "day", "24h")).toBe("14:00");
  });

  it("Verify month granularity labels by month name", () => {
    expect(formatBucketLabel("2026-05-01", "month")).toBe("May");
  });

  it("Verify week granularity labels by the week's start date", () => {
    expect(formatBucketLabel("2026-08-17", "week")).toBe("8/17");
  });

  it("Verify an unparseable bucket falls back to the raw key", () => {
    expect(formatBucketLabel("not-a-date", "day")).toBe("not-a-date");
  });
});

describe("rangeLabel", () => {
  it("Verify every range has a human caption", () => {
    expect(rangeLabel("24h")).toBe("Last 24 hours");
    expect(rangeLabel("quarter")).toBe("This quarter");
  });
});
