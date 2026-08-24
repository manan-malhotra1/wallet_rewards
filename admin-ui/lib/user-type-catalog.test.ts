import { describe, expect, it } from "vitest";

import { groupTypesByCategory, topLevelTypes, userTypeLabel } from "@/lib/user-type-catalog";
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
