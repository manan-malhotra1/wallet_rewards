/**
 * Unit tests for the glassmorphism token generator.
 *
 * These prove that `deriveGlassTokens` produces well-formed CSS values
 * (gradient images, rgba tints, blur radii) for both colour schemes, that
 * atmosphere blob alphas stay within the spec bounds (dark ≤ 0.55, light ≤
 * 0.25), that the derivation actually re-tints per tenant rather than
 * collapsing to a brand-invariant constant, that `glassVarsCss` emits every
 * token, and — the sync guard — that the static Ocean defaults baked into
 * `app/globals.css` have not drifted from `deriveGlassTokens(DEFAULT_ACCENT,
 * DEFAULT_LIGHT)`.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, it, expect } from "vitest";

import { deriveGlassTokens, glassVarsCss, GLASS_VAR_NAMES, type GlassTokens } from "./glass-tokens";

/** Matches an uppercase `#RRGGBB` string. */
const HEX = /^#[0-9A-F]{6}$/;

/** Pull every `rgba(..., A)` alpha out of a gradient-image string. */
function alphas(image: string): number[] {
  return [...image.matchAll(/rgba\(\d+, \d+, \d+, ([0-9.]+)\)/g)].map((m) =>
    parseFloat(m[1]),
  );
}

/** Parse an `rgba(r, g, b, a)` string into its numeric components. */
function parseRgba(value: string): { r: number; g: number; b: number; a: number } {
  const m = value.match(/^rgba\((\d+), (\d+), (\d+), ([0-9.]+)\)$/);
  if (!m) throw new Error(`Not an rgba() string: "${value}"`);
  return { r: Number(m[1]), g: Number(m[2]), b: Number(m[3]), a: Number(m[4]) };
}

describe("deriveGlassTokens", () => {
  it("Verify it derives gradient images, tints and blur radii for both schemes", () => {
    const g = deriveGlassTokens();
    for (const scheme of [g.dark, g.light]) {
      expect(scheme.atmosphereImage).toMatch(/^radial-gradient\(/);
      expect(scheme.atmosphereImage.match(/radial-gradient\(/g)).toHaveLength(3);
      expect(scheme.atmosphereBase).toMatch(HEX);
      expect(scheme.panel).toMatch(/^rgba\(/);
      expect(scheme.overlay).toMatch(/^rgba\(/);
      expect(scheme.border).toMatch(/^rgba\(/);
      expect(scheme.blurPanel).toBe("14px");
      expect(scheme.blurOverlay).toBe("18px");
    }
  });

  it("Verify it keeps atmosphere blob alphas within the spec bounds", () => {
    const g = deriveGlassTokens();
    // Spec §2: dark blob alphas ≤ 0.55, light blob alphas ≤ 0.25.
    const darkAlphas = alphas(g.dark.atmosphereImage);
    const lightAlphas = alphas(g.light.atmosphereImage);
    expect(darkAlphas).toHaveLength(3);
    expect(lightAlphas).toHaveLength(3);
    for (const a of darkAlphas) expect(a).toBeLessThanOrEqual(0.55);
    for (const a of lightAlphas) expect(a).toBeLessThanOrEqual(0.25);
  });

  it("Verify the dark atmosphere base stays brand-tinted", () => {
    // Guards against darken(accent, 0.9)-style regressions, which collapse to
    // a brand-invariant near-black (#000001) regardless of the tenant accent.
    const ocean = deriveGlassTokens();
    const berry = deriveGlassTokens("#7A1F1F", "#FFFFFF");
    expect(ocean.dark.atmosphereBase).not.toBe(berry.dark.atmosphereBase);
  });

  it("Verify it re-tints with the tenant brand and differs between schemes", () => {
    const ocean = deriveGlassTokens();
    const berry = deriveGlassTokens("#243B8F", "#FFF0C9");
    expect(berry.dark.atmosphereImage).not.toBe(ocean.dark.atmosphereImage);
    expect(ocean.dark.atmosphereImage).not.toBe(ocean.light.atmosphereImage);

    // Dark overlay must occlude (near-opaque) and carry the brand hue rather
    // than being pure white — assert the behaviour, not a specific formula.
    const oceanOverlay = parseRgba(ocean.dark.overlay);
    expect(oceanOverlay.a).toBeGreaterThanOrEqual(0.7);
    expect([oceanOverlay.r, oceanOverlay.g, oceanOverlay.b]).not.toEqual([255, 255, 255]);
    expect(berry.dark.overlay).not.toBe(ocean.dark.overlay);
  });
});

describe("glassVarsCss", () => {
  it("Verify it emits all 9 --glass-* declarations", () => {
    const css = glassVarsCss(deriveGlassTokens().light);
    // GLASS_VAR_NAMES is the single source of truth for field -> CSS name;
    // iterate it so a field added to GlassTokens without a var name (a
    // compile error) or dropped from emission (this assertion) both fail
    // loudly instead of silently shipping a partial token set.
    const names = Object.values(GLASS_VAR_NAMES);
    expect(names).toHaveLength(9);
    for (const name of names) {
      expect(css).toContain(`--${name}:`);
    }
    expect(css.match(/--glass-/g)).toHaveLength(9);
  });
});

/** Collapse whitespace and case so CSS-file formatting (line breaks, the
 * deliberate lowercase hex in globals.css) can't cause a false-positive
 * diff against the JS-derived values. */
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

describe("globals.css sync guard", () => {
  // Reads admin-ui/app/globals.css relative to this test file. If someone
  // hand-edits the static --glass-* defaults there without re-running
  // `deriveGlassTokens(DEFAULT_ACCENT, DEFAULT_LIGHT)` (see the sync comment
  // above each block in that file), this test goes red instead of the
  // drift going unnoticed until a tenant with no brand override renders a
  // stale atmosphere.
  const cssPath = path.join(__dirname, "../app/globals.css");
  const css = fs.readFileSync(cssPath, "utf-8");
  const rootBlock = normalizeCss(extractBlock(css, ":root"));
  const darkBlock = normalizeCss(extractBlock(css, "\\.dark"));

  it("Verify :root's static glass defaults match deriveGlassTokens(...).light verbatim", () => {
    const light: GlassTokens = deriveGlassTokens().light;
    for (const value of Object.values(light)) {
      expect(rootBlock).toContain(normalizeCss(value));
    }
  });

  it("Verify .dark's static glass defaults match deriveGlassTokens(...).dark verbatim", () => {
    const dark: GlassTokens = deriveGlassTokens().dark;
    for (const value of Object.values(dark)) {
      expect(darkBlock).toContain(normalizeCss(value));
    }
  });
});
