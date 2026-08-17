import { describe, expect, it } from "vitest";

import {
  areaPath,
  bandCentres,
  bandTicks,
  barPath,
  gridLines,
  nearestIndex,
  niceMax,
  ringPath,
  smoothPath,
  xAt,
  xTicks,
  yAt,
  type PlotRect,
} from "./chart-geometry";

const RECT: PlotRect = { x: 50, y: 10, width: 900, height: 200 };

describe("xAt", () => {
  it("Verify a single point is centred rather than pinned to the left edge", () => {
    expect(xAt(0, 1, RECT)).toBe(500);
  });

  it("Verify the first and last points land on the plot edges", () => {
    expect(xAt(0, 5, RECT)).toBe(50);
    expect(xAt(4, 5, RECT)).toBe(950);
  });
});

describe("yAt", () => {
  it("Verify the domain maximum maps to the top of the plot and zero to the bottom", () => {
    expect(yAt(100, 0, 100, RECT)).toBe(10);
    expect(yAt(0, 0, 100, RECT)).toBe(210);
  });

  it("Verify a zero-width domain pins to the baseline instead of dividing by zero", () => {
    expect(yAt(7, 7, 7, RECT)).toBe(210);
  });
});

describe("smoothPath", () => {
  it("Verify an empty series yields an empty path that is safe to render", () => {
    expect(smoothPath([], RECT, 10)).toBe("");
  });

  it("Verify a single point yields a bare move with no curve segment", () => {
    expect(smoothPath([5], RECT, 10)).toBe("M500.00 110.00");
  });

  it("Verify each additional point adds exactly one cubic segment", () => {
    const path = smoothPath([1, 2, 3, 4], RECT, 4);
    expect(path.match(/C/g)).toHaveLength(3);
  });

  it("Verify control points never push the curve past a data point's value", () => {
    // Both control points of each segment carry a neighbour's own y, so the
    // curve is bounded by the two points it joins — no overshoot below zero
    // between two positive buckets.
    const ys = smoothPath([10, 0, 10], RECT, 10)
      .split(/[MC,]/)
      .map((pair) => pair.trim())
      .filter(Boolean)
      .map((pair) => Number(pair.split(/\s+/)[1]));
    expect(ys.length).toBeGreaterThan(0);
    expect(Math.max(...ys)).toBeLessThanOrEqual(RECT.y + RECT.height);
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(RECT.y);
  });
});

describe("areaPath", () => {
  it("Verify the fill closes down to the baseline and back to the left edge", () => {
    const area = areaPath(smoothPath([1, 2], RECT, 2), RECT);
    expect(area.endsWith("L950.00 210.00 L50.00 210.00 Z")).toBe(true);
  });

  it("Verify an empty line produces no area rather than a stray triangle", () => {
    expect(areaPath("", RECT)).toBe("");
  });
});

describe("barPath", () => {
  it("Verify a positive bar grows upward from the baseline", () => {
    expect(barPath(0, 100, 10, 40, 3)).toContain("M0.00 100.00");
    expect(barPath(0, 100, 10, 40, 3)).toContain("63.00");
  });

  it("Verify a negative bar grows downward from the same baseline", () => {
    expect(barPath(0, 100, 10, -40, 3)).toContain("137.00");
  });

  it("Verify the corner radius is clamped so a short bar cannot invert its curves", () => {
    // radius 8 exceeds both half-width (5) and the bar height (2).
    expect(() => barPath(0, 100, 10, 2, 8)).not.toThrow();
    expect(barPath(0, 100, 10, 2, 8)).toContain("100.00");
  });
});

describe("ringPath", () => {
  it("Verify a segment over 180 degrees sets the large-arc flag", () => {
    expect(ringPath(50, 50, 40, 20, 0, 300)).toContain("A40 40 0 1 1");
  });

  it("Verify a small segment leaves the large-arc flag clear", () => {
    expect(ringPath(50, 50, 40, 20, 0, 90)).toContain("A40 40 0 0 1");
  });
});

describe("niceMax", () => {
  it.each([
    [0, 1],
    [-5, 1],
    [0.8, 1],
    [1200, 2000],
    [2400, 2500],
    [4100, 5000],
    [9000, 10000],
  ])("Verify %s rounds up to the readable axis bound %s", (input, expected) => {
    expect(niceMax(input)).toBe(expected);
  });
});

describe("gridLines", () => {
  it("Verify count+1 lines span the plot from baseline to the domain maximum", () => {
    const lines = gridLines(100, RECT, 4);
    expect(lines).toHaveLength(5);
    expect(lines[0]).toEqual({ y: 210, value: 0 });
    expect(lines[4]).toEqual({ y: 10, value: 100 });
  });
});

describe("xTicks", () => {
  it("Verify labels are thinned to at most the requested tick count", () => {
    const ticks = xTicks(Array.from({ length: 90 }, (_, i) => `d${i}`), RECT, 8);
    expect(ticks.length).toBeLessThanOrEqual(8);
    expect(ticks[0].label).toBe("d0");
  });

  it("Verify a short series keeps every label", () => {
    expect(xTicks(["a", "b", "c"], RECT, 8)).toHaveLength(3);
  });

  it("Verify no labels yields no ticks", () => {
    expect(xTicks([], RECT, 8)).toEqual([]);
  });
});

describe("bandCentres", () => {
  it("Verify bars are centred in their band rather than on the plot edges", () => {
    const centres = bandCentres(3, { x: 0, y: 0, width: 300, height: 100 });
    expect(centres).toEqual([50, 150, 250]);
  });

  it("Verify an empty series has no bands", () => {
    expect(bandCentres(0, RECT)).toEqual([]);
  });
});

describe("bandTicks", () => {
  it("Verify banded ticks are thinned and sit on band centres", () => {
    const ticks = bandTicks(["a", "b", "c", "d"], { x: 0, y: 0, width: 400, height: 10 }, 2);
    expect(ticks).toHaveLength(2);
    expect(ticks[0]).toEqual({ x: 50, label: "a" });
  });
});

describe("nearestIndex", () => {
  it("Verify a pointer inside the plot snaps to the closest bucket", () => {
    expect(nearestIndex(50, 5, RECT)).toBe(0);
    expect(nearestIndex(950, 5, RECT)).toBe(4);
    expect(nearestIndex(500, 5, RECT)).toBe(2);
  });

  it("Verify a pointer outside the plot clamps rather than returning an invalid index", () => {
    expect(nearestIndex(-400, 5, RECT)).toBe(0);
    expect(nearestIndex(5000, 5, RECT)).toBe(4);
  });

  it("Verify a single-bucket series always resolves to index zero", () => {
    expect(nearestIndex(123, 1, RECT)).toBe(0);
  });
});
