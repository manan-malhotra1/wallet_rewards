import { describe, expect, it } from "vitest";

import { seriesColor, CHART_SERIES } from "./chart-colors";

describe("chart-colors", () => {
  it("returns a stable color per series index, wrapping around", () => {
    expect(seriesColor(0)).toBe(CHART_SERIES[0]);
    expect(seriesColor(CHART_SERIES.length)).toBe(CHART_SERIES[0]); // wraps
  });
});
