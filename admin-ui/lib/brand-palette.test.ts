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
import fs from "node:fs";
import path from "node:path";

import { describe, it, expect } from "vitest";

import {
  ramp,
  deriveTokens,
  hexToRgba,
  GOLDEN_STOPS,
  DEFAULT_ACCENT,
  DEFAULT_LIGHT,
  type TokenKey,
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

/** Collapse whitespace and case so CSS-file formatting (line breaks, the
 * deliberate lowercase hex in globals.css) can't cause a false-positive
 * diff against the JS-derived values. Mirrors the helper in
 * `glass-tokens.test.ts`'s sync guard. */
function normalizeCss(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase();
}

/** Extract the declaration body of a top-level `selector { ... }` block
 * (assumes no nested braces inside it, true for `:root`/`.dark` in
 * globals.css). */
function extractBlock(css: string, selector: string): string {
  const match = css.match(new RegExp(`${selector}\\s*\\{([^}]*)\\}`));
  if (!match) throw new Error(`Could not find "${selector} { ... }" block`);
  return match[1];
}

describe("globals.css palette sync guard", () => {
  // Reads admin-ui/app/globals.css relative to this test file. If someone
  // hand-edits the static shadcn token defaults there without re-running
  // deriveTokens(DEFAULT_ACCENT, DEFAULT_LIGHT), this test goes red instead
  // of the drift going unnoticed until a tenant with no brand override
  // renders a stale palette (the sidebar retokening is exactly the kind of
  // hand-edit this guards against).
  const cssPath = path.join(__dirname, "../app/globals.css");
  const css = fs.readFileSync(cssPath, "utf-8");
  const rootBlock = normalizeCss(extractBlock(css, ":root"));
  const darkBlock = normalizeCss(extractBlock(css, "\\.dark"));

  // Asserts the NAME is bound to the VALUE (`--card: #02263e;`), not just
  // that the value string happens to occur somewhere in the block — same
  // rationale as glass-tokens.test.ts's expectVarBound.
  function expectTokenBound(block: string, name: TokenKey, tokens: TokenMap): void {
    expect(block).toContain(normalizeCss(`--${name}: ${tokens[name]};`));
  }

  it("Verify :root's static token defaults bind each --<token> name to deriveTokens(...).light's value", () => {
    const light: TokenMap = deriveTokens(DEFAULT_ACCENT, DEFAULT_LIGHT).light;
    for (const key of Object.keys(light) as TokenKey[]) {
      expectTokenBound(rootBlock, key, light);
    }
  });

  it("Verify .dark's static token defaults bind each --<token> name to deriveTokens(...).dark's value", () => {
    const dark: TokenMap = deriveTokens(DEFAULT_ACCENT, DEFAULT_LIGHT).dark;
    for (const key of Object.keys(dark) as TokenKey[]) {
      expectTokenBound(darkBlock, key, dark);
    }
  });
});
