/**
 * Pure helpers over the user-type catalog. No fetching — the caller supplies
 * the payload so these stay trivially testable.
 */
import type {
  UserTypeCatalog,
  UserTypeCategoryOption,
  UserTypeOption,
} from "@/lib/api-types";

/** A category with the types that belong to it, parents before their children. */
export interface CategoryGroup {
  category: UserTypeCategoryOption;
  types: UserTypeOption[];
}

/**
 * Group types under their category, categories in display order and, within a
 * category, top-level types before the children that hang off them.
 *
 * @param catalog - The catalog payload straight off the endpoint.
 * @returns One group per category, in `display_order`.
 */
export function groupTypesByCategory(catalog: UserTypeCatalog): CategoryGroup[] {
  return [...catalog.categories]
    .sort((a, b) => a.display_order - b.display_order)
    .map((category) => ({
      category,
      types: catalog.types
        .filter((t) => t.category_code === category.code)
        .sort((a, b) => {
          // Parents first, then alphabetical — mirrors the indented list.
          const depth = Number(!!a.parent_type_code) - Number(!!b.parent_type_code);
          return depth !== 0 ? depth : a.label.localeCompare(b.label);
        }),
    }));
}

/**
 * The types that may be chosen as a parent in `categoryCode`: active,
 * top-level, same category. A child type is never offered, which is the
 * two-level cap expressed in the UI before the server ever refuses it.
 *
 * @param catalog - The catalog payload straight off the endpoint.
 * @param categoryCode - The category the new child type will live in.
 * @returns Candidate parent types, empty for a flat category.
 */
export function topLevelTypes(
  catalog: UserTypeCatalog,
  categoryCode: string,
): UserTypeOption[] {
  const category = catalog.categories.find((c) => c.code === categoryCode);
  if (!category?.supports_hierarchy) return [];
  return catalog.types.filter(
    (t) =>
      t.category_code === categoryCode &&
      !t.parent_type_code &&
      t.status === "active",
  );
}

/**
 * Human label for a user-type code.
 *
 * The catalog is the source of truth. When it cannot answer — it failed to
 * load, or the code belongs to a type retired out of the visible set — the
 * code is title-cased rather than shown raw, so `head_merchant` still reads as
 * "Head merchant" on a surface that has no catalog to hand. There is
 * deliberately no hardcoded map of type codes here: that is what made every
 * custom type render as its own code.
 *
 * @param catalog - The catalog payload, or null when it could not be loaded.
 * @param code - The stored type code.
 * @returns The catalog label, else the title-cased code, else an em dash.
 */
export function userTypeLabel(
  catalog: UserTypeCatalog | null | undefined,
  code: string | null | undefined,
): string {
  if (!code) return "—";
  const known = catalog?.types.find((t) => t.code === code);
  if (known) return known.label;
  const words = code.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
