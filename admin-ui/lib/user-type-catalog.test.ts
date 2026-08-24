import { describe, expect, it } from "vitest";

import {
  deriveUserTypeCode,
  groupTypesByCategory,
  topLevelTypes,
  userTypeLabel,
} from "@/lib/user-type-catalog";
import type { UserTypeCatalog } from "@/lib/api-types";

const catalog: UserTypeCatalog = {
  categories: [
    { code: "consumer", label: "Consumers", display_order: 1, supports_hierarchy: false },
    { code: "retail", label: "Retail", display_order: 2, supports_hierarchy: true },
  ],
  types: [
    { code: "consumer", label: "Consumer", category_code: "consumer", parent_type_code: null,
      is_system: true, status: "active" },
    { code: "super_agent", label: "Super agent", category_code: "retail", parent_type_code: null,
      is_system: true, status: "active" },
    { code: "agent", label: "Agent", category_code: "retail", parent_type_code: "super_agent",
      is_system: true, status: "active" },
  ],
};

describe("user-type catalog helpers", () => {
  it("groups types under their category in display order", () => {
    const grouped = groupTypesByCategory(catalog);
    expect(grouped.map((g) => g.category.code)).toEqual(["consumer", "retail"]);
    expect(grouped[1].types.map((t) => t.code)).toEqual(["super_agent", "agent"]);
  });

  it("offers only top-level types as parent candidates", () => {
    // 'agent' is a child, so it must never be offered as somebody's parent —
    // this is the two-level cap expressed in the UI.
    expect(topLevelTypes(catalog, "retail").map((t) => t.code)).toEqual(["super_agent"]);
  });

  it("returns no parent candidates for a flat category", () => {
    expect(topLevelTypes(catalog, "consumer")).toEqual([]);
  });

  it("labels from the catalog, and title-cases a code it cannot resolve", () => {
    expect(userTypeLabel(catalog, "super_agent")).toBe("Super agent");
    // Unknown to this catalog (retired, or the catalog failed to load): still
    // readable, and never a hardcoded map that would miss a custom type.
    expect(userTypeLabel(catalog, "bureau_de_change")).toBe("Bureau de change");
    expect(userTypeLabel(null, "head_merchant")).toBe("Head merchant");
    expect(userTypeLabel(catalog, null)).toBe("—");
  });
});

/** A catalog whose types are the codes a derivation must not collide with. */
function catalogOfCodes(codes: string[]): UserTypeCatalog {
  return {
    categories: catalog.categories,
    types: codes.map((code) => ({
      code,
      label: code,
      category_code: "retail",
      parent_type_code: null,
      is_system: false,
      status: "active" as const,
    })),
  };
}

/** The shape the backend enforces on `code` (min 2, max 20, snake_case). */
const BACKEND_CODE_PATTERN = /^[a-z][a-z0-9_]*$/;

describe("deriveUserTypeCode", () => {
  const empty = catalogOfCodes([]);

  it("slugifies a label into lowercase snake_case", () => {
    expect(deriveUserTypeCode("Junior Agent", empty)).toBe("junior_agent");
    expect(deriveUserTypeCode("Field  Agent (North)", empty)).toBe("field_agent_north");
    expect(deriveUserTypeCode("  Spaced  out  ", empty)).toBe("spaced_out");
    expect(deriveUserTypeCode("Tier-2 Agent", empty)).toBe("tier_2_agent");
  });

  it("prefixes the fallback when the slug cannot start a legal code", () => {
    // The backend pattern demands a leading lowercase letter and 2+ chars.
    expect(deriveUserTypeCode("9 Lives", empty)).toBe("type_9_lives");
    expect(deriveUserTypeCode("2026 Cohort", empty)).toBe("type_2026_cohort");
    expect(deriveUserTypeCode("!!!", empty)).toBe("type");
    expect(deriveUserTypeCode("   ", empty)).toBe("type");
    expect(deriveUserTypeCode("A", empty)).toBe("type_a");
  });

  it("caps at 20 characters, cutting at a word boundary", () => {
    expect(deriveUserTypeCode("Extraordinarily Long Type", empty)).toBe(
      "extraordinarily_long",
    );
    expect(deriveUserTypeCode("Field Agent North Region", empty)).toBe(
      "field_agent_north",
    );
    expect(deriveUserTypeCode("Regional Distribution Partner", empty)).toBe(
      "regional",
    );
  });

  it("cuts mid-word when no boundary leaves a usable stem", () => {
    // One long word: there is no boundary to cut at.
    expect(deriveUserTypeCode("Antidisestablishmentarianism", empty)).toBe(
      "antidisestablishment",
    );
    // The only boundary would leave "ab" — too little to identify the type.
    expect(deriveUserTypeCode("Ab Superlongwordthatkeepsgoing", empty)).toBe(
      "ab_superlongwordthat",
    );
  });

  it("de-duplicates against system, tenant and retired codes alike", () => {
    // 'agent' is a seeded system type in the real catalog.
    expect(deriveUserTypeCode("Agent", catalog)).toBe("agent_2");

    const retired: UserTypeCatalog = {
      categories: catalog.categories,
      types: [
        {
          code: "bureau_de_change",
          label: "Bureau de change",
          category_code: "retail",
          parent_type_code: null,
          is_system: false,
          status: "retired",
        },
      ],
    };
    // A retired code is still taken — the join key never gets freed.
    expect(deriveUserTypeCode("Bureau de change", retired)).toBe("bureau_de_change_2");
  });

  it("keeps counting past the first collision", () => {
    const taken = catalogOfCodes(["agent", "agent_2", "agent_3"]);
    expect(deriveUserTypeCode("Agent", taken)).toBe("agent_4");
  });

  it("truncates the stem further so the suffix still fits in 20", () => {
    const taken = catalogOfCodes(["abcdefghij_klmnopqrs"]);
    const code = deriveUserTypeCode("Abcdefghij Klmnopqrs", taken);
    expect(code).toBe("abcdefghij_klmnopq_2");
    expect(code).toHaveLength(20);
  });

  it("never leaves a doubled underscore where the stem was cut", () => {
    const taken = catalogOfCodes(["abcdefghijklmnopq_rs"]);
    const code = deriveUserTypeCode("Abcdefghijklmnopq Rs", taken);
    expect(code).toBe("abcdefghijklmnopq_2");
    expect(code).not.toMatch(/__/);
  });

  it("stays inside 20 characters when the suffix grows two digits", () => {
    const stem = "abcdefghij_klmnopqrs";
    const taken = catalogOfCodes([
      stem,
      ...Array.from({ length: 8 }, (_, i) => `abcdefghij_klmnopq_${i + 2}`),
    ]);
    const code = deriveUserTypeCode("Abcdefghij Klmnopqrs", taken);
    expect(code).toBe("abcdefghij_klmnop_10");
    expect(code.length).toBeLessThanOrEqual(20);
  });

  it("always emits a code the backend will accept", () => {
    const labels = [
      "Junior Agent",
      "9 Lives",
      "!!!",
      "A",
      "Antidisestablishmentarianism",
      "Head Mer",
      "Étoile Café",
      "___",
      "Agent",
      "Field  Agent (North)",
    ];
    for (const label of labels) {
      const code = deriveUserTypeCode(label, catalog);
      expect(code, label).toMatch(BACKEND_CODE_PATTERN);
      expect(code.length, label).toBeGreaterThanOrEqual(2);
      expect(code.length, label).toBeLessThanOrEqual(20);
    }
  });
});
