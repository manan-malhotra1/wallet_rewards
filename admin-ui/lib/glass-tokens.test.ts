/**
 * Unit tests for the glassmorphism token generator.
 *
 * These prove that `deriveGlassTokens` produces well-formed CSS values
 * (gradient images, rgba tints, blur radii) for both colour schemes, that
 * atmosphere blob alphas stay within the spec bounds (dark ≤ 0.55, light ≤
 * 0.25), and that the derivation actually re-tints per tenant rather than
 * collapsing to a brand-invariant constant.
 */
import { describe, it, expect } from "vitest";

import { deriveGlassTokens } from "./glass-tokens";

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
