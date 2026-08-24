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

/**
 * The backend caps `code` at 20 characters (the width of `users.user_type` and
 * of the `user_type` column on every config table) and demands
 * `^[a-z][a-z0-9_]*$` with a 2-character minimum. Derivation has to land inside
 * that envelope or the proposal is rejected with a 422 the operator never asked
 * for.
 */
const CODE_MAX_LENGTH = 20;

/**
 * A word-boundary cut is only worth taking if a recognisable word survives it.
 * "ab_superlongword…" cut at its only underscore would leave "ab", which
 * identifies nothing — better to cut mid-word and keep the shape of the label.
 */
const MIN_BOUNDARY_STEM = 4;

/** Prefix that rescues a slug the backend pattern would refuse. */
const FALLBACK_PREFIX = "type";

/** Lowercase, collapse every run of non-alphanumerics to one underscore, trim. */
function slugify(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

/**
 * Cut a slug down to `max`, preferring a word boundary over a mid-word chop.
 *
 * @param slug - An already-slugified string.
 * @param max - The character budget.
 * @returns The slug, at most `max` characters, without a trailing underscore.
 */
function truncateAtWord(slug: string, max: number): string {
  if (slug.length <= max) return slug;
  const head = slug.slice(0, max);
  // The next character being the separator means `head` is already whole words.
  if (slug[max] === "_") return head;
  const boundary = head.lastIndexOf("_");
  const cut = boundary >= MIN_BOUNDARY_STEM ? head.slice(0, boundary) : head;
  return cut.replace(/_+$/, "");
}

/**
 * Derive the machine code for a new user type from the label an operator typed.
 *
 * The code is not an operator-facing concept — it is the join key written to
 * `users.user_type` and every config row, and the maker-checker scope key — so
 * it is computed rather than asked for. Codes are immutable once created (spec
 * D5): call this on the create path only, never when relabelling a live type.
 *
 * Rules:
 * - Lowercase; every run of non-alphanumerics becomes one underscore; leading
 *   and trailing underscores are trimmed. "Field  Agent (North)" →
 *   `field_agent_north`.
 * - **Fallback**: a slug that cannot open a legal code — empty, starting with a
 *   digit, or under the backend's 2-character minimum — is prefixed with
 *   `type_`. "9 Lives" → `type_9_lives`; "!!!" → `type`; "A" → `type_a`.
 * - Capped at 20 characters, cut at the last underscore inside the budget when
 *   that still leaves 4 characters, otherwise cut mid-word. "Regional
 *   Distribution Partner" → `regional`.
 * - De-duplicated against every code in the catalog — system types, the
 *   tenant's own, and retired ones, because a retired code is still taken. On a
 *   collision `_2`, `_3`, … is appended and the stem is hard-cut (no word
 *   boundary — it would collapse distinct labels onto one stem) so the total
 *   never exceeds 20.
 *
 * @param label - The human label the operator typed.
 * @param catalog - The tenant's catalog, retired types included.
 * @returns A code matching `^[a-z][a-z0-9_]*$`, 2–20 characters, unused.
 */
export function deriveUserTypeCode(label: string, catalog: UserTypeCatalog): string {
  const slug = slugify(label);
  const legal = /^[a-z]/.test(slug) && slug.length >= 2 ? slug : `${FALLBACK_PREFIX}_${slug}`;
  const base = truncateAtWord(legal.replace(/_+$/, ""), CODE_MAX_LENGTH);

  const taken = new Set(catalog.types.map((t) => t.code.toLowerCase()));
  if (!taken.has(base)) return base;

  for (let n = 2; ; n += 1) {
    const suffix = `_${n}`;
    const stem = base.slice(0, CODE_MAX_LENGTH - suffix.length).replace(/_+$/, "");
    const candidate = `${stem}${suffix}`;
    if (!taken.has(candidate)) return candidate;
  }
}
