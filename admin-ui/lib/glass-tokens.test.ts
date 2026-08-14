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

describe("deriveGlassTokens transparency slider", () => {
  it("Verify the default transparency (50) matches the explicit t=50 call", () => {
    // The caller-side default (TenantThemeStyle etc. coerce null -> 50) must
    // be indistinguishable from omitting the argument entirely.
    const implicit = deriveGlassTokens();
    const explicit = deriveGlassTokens(undefined, undefined, 50);
    expect(explicit).toEqual(implicit);
  });

  it("Verify a higher transparency produces a lower panel alpha in both schemes", () => {
    const low = deriveGlassTokens(undefined, undefined, 0);
    const high = deriveGlassTokens(undefined, undefined, 100);
    expect(parseRgba(high.light.panel).a).toBeLessThan(parseRgba(low.light.panel).a);
    expect(parseRgba(high.dark.panel).a).toBeLessThan(parseRgba(low.dark.panel).a);
  });

  it("Verify t=0 and t=100 hit the documented panel alpha bounds", () => {
    const t0 = deriveGlassTokens(undefined, undefined, 0);
    const t50 = deriveGlassTokens(undefined, undefined, 50);
    const t100 = deriveGlassTokens(undefined, undefined, 100);
    expect(parseRgba(t0.light.panel).a).toBeCloseTo(0.8, 3);
    expect(parseRgba(t50.light.panel).a).toBeCloseTo(0.4, 3);
    expect(parseRgba(t100.light.panel).a).toBeCloseTo(0.08, 3);
    expect(parseRgba(t0.dark.panel).a).toBeCloseTo(0.08, 3);
    expect(parseRgba(t50.dark.panel).a).toBeCloseTo(0.04, 3);
    expect(parseRgba(t100.dark.panel).a).toBeCloseTo(0.01, 3);
  });

  it("Verify an out-of-range transparency clamps to the same floor as t=100", () => {
    // t=200 pushes the raw linear value well past the floor; the clamp on
    // the OUTPUT (not the input) means it still lands exactly on the t=100
    // alpha rather than continuing to fall or erroring.
    const overshoot = deriveGlassTokens(undefined, undefined, 200);
    const floor = deriveGlassTokens(undefined, undefined, 100);
    expect(overshoot.light.panel).toBe(floor.light.panel);
    expect(overshoot.dark.panel).toBe(floor.dark.panel);
  });

  it("Verify only the panel tint changes with transparency — overlay/border/blur stay fixed", () => {
    // Floating-surface occlusion is a readability invariant (spec): only
    // .glass-panel is tunable, never .glass-overlay/border/blur.
    const t0 = deriveGlassTokens(undefined, undefined, 0);
    const t100 = deriveGlassTokens(undefined, undefined, 100);
    for (const scheme of ["light", "dark"] as const) {
      expect(t100[scheme].overlay).toBe(t0[scheme].overlay);
      expect(t100[scheme].border).toBe(t0[scheme].border);
      expect(t100[scheme].blurPanel).toBe(t0[scheme].blurPanel);
      expect(t100[scheme].blurOverlay).toBe(t0[scheme].blurOverlay);
    }
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

  // Asserts the NAME is bound to the VALUE (`--glass-blur-panel: 14px;`),
  // not just that the value string happens to occur somewhere in the block.
  // A bare value-presence check can't catch two vars' values being swapped
  // (e.g. blur-panel/blur-overlay) since both values would still be present
  // in the block, just under the wrong name — the trailing `;` also stops a
  // short value being satisfied as a prefix of a longer one.
  function expectVarBound(block: string, field: keyof GlassTokens, tokens: GlassTokens): void {
    const name = GLASS_VAR_NAMES[field];
    expect(block).toContain(normalizeCss(`--${name}: ${tokens[field]};`));
  }

  it("Verify :root's static glass defaults bind each --glass-* name to deriveGlassTokens(...).light's value", () => {
    const light: GlassTokens = deriveGlassTokens().light;
    for (const field of Object.keys(GLASS_VAR_NAMES) as (keyof GlassTokens)[]) {
      expectVarBound(rootBlock, field, light);
    }
  });

  it("Verify .dark's static glass defaults bind each --glass-* name to deriveGlassTokens(...).dark's value", () => {
    const dark: GlassTokens = deriveGlassTokens().dark;
    for (const field of Object.keys(GLASS_VAR_NAMES) as (keyof GlassTokens)[]) {
      expectVarBound(darkBlock, field, dark);
    }
  });
});
