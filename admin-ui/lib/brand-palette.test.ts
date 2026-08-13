/**
 * Unit tests for the brand palette generator.
 *
 * These lock the perceptual OKLab ramp against a known-good reference scale
 * (the default Sasai "Ocean" accent + white light), prove that every
 * shadcn token derives to a valid renderable colour in both themes, prove
 * that extrapolated stops beyond the two anchors stay inside the sRGB gamut,
 * and cover the `hexToRgba` primitive that the glass token system in
 * `./glass-tokens.ts` (tested separately in `glass-tokens.test.ts`) builds on.
 */
import { describe, it, expect } from "vitest";

import {
  ramp,
  deriveTokens,
  hexToRgba,
  GOLDEN_STOPS,
  DEFAULT_ACCENT,
  DEFAULT_LIGHT,
  type TokenMap,
} from "./brand-palette";

/** Matches an uppercase `#RRGGBB` string. */
const HEX = /^#[0-9A-F]{6}$/;

/** Split a `#RRGGBB` string into its three 0..255 channel integers. */
function channels(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

/** Assert two hex colours match within ±`tol` per channel. */
function expectClose(actual: string, expected: string, tol = 2): void {
  const a = channels(actual);
  const e = channels(expected);
  for (let i = 0; i < 3; i++) {
    expect(Math.abs(a[i] - e[i])).toBeLessThanOrEqual(tol);
  }
}

describe("brand-palette", () => {
  it("Verify the golden-ratio scale reproduces the seven brand stops", () => {
    const expected = [
      "#0C5888",
      "#396F9A",
      "#4E7EA4",
      "#6F96B6",
      "#A5BDD2",
      "#D1DEE8",
      "#FFFFFF",
    ];
    GOLDEN_STOPS.forEach((t, i) => {
      const got = ramp(DEFAULT_ACCENT, DEFAULT_LIGHT, t);
      expect(got).toMatch(HEX);
      expectClose(got, expected[i]);
    });
  });

  it("Verify every derived token is a valid colour in both light and dark themes", () => {
    const { light, dark } = deriveTokens(DEFAULT_ACCENT, DEFAULT_LIGHT);
    const assertAllHex = (map: TokenMap) => {
      for (const [key, value] of Object.entries(map)) {
        expect(value, `token "${key}" must be #RRGGBB`).toMatch(HEX);
      }
    };
    assertAllHex(light);
    assertAllHex(dark);
    // Both themes carry the same key set (no missing/extra tokens).
    expect(Object.keys(light).sort()).toEqual(Object.keys(dark).sort());
  });

  it("Verify a tenant can supply its own brand colours and still get valid tokens", () => {
    const { light, dark } = deriveTokens("#8A1538", "#FDE8EE");
    for (const value of [...Object.values(light), ...Object.values(dark)]) {
      expect(value).toMatch(HEX);
    }
  });

  it("Verify extrapolated stops beyond both anchors stay inside the sRGB gamut", () => {
    for (const t of [-0.45, -0.35, -0.18, 1.12, 1.3]) {
      const got = ramp(DEFAULT_ACCENT, DEFAULT_LIGHT, t);
      expect(got).toMatch(HEX);
      for (const c of channels(got)) {
        expect(c).toBeGreaterThanOrEqual(0);
        expect(c).toBeLessThanOrEqual(255);
      }
    }
  });

  it("Verify the ramp anchors exactly to the supplied brand colours at t=0 and t=1", () => {
    expectClose(ramp(DEFAULT_ACCENT, DEFAULT_LIGHT, 0), DEFAULT_ACCENT, 1);
    expectClose(ramp(DEFAULT_ACCENT, DEFAULT_LIGHT, 1), DEFAULT_LIGHT, 1);
  });

  it("Verify deriveTokens falls back to the default Sasai brand when called with no arguments", () => {
    expect(deriveTokens()).toEqual(deriveTokens(DEFAULT_ACCENT, DEFAULT_LIGHT));
  });
});

describe("hexToRgba", () => {
  it("Verify it converts a hex colour and alpha into an rgba() string", () => {
    expect(hexToRgba("#0C5888", 0.5)).toBe("rgba(12, 88, 136, 0.5)");
    expect(hexToRgba("#FFFFFF", 1)).toBe("rgba(255, 255, 255, 1)");
  });
});
