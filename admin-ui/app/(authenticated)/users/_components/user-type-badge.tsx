/**
 * User-type presentation helpers (Epic 13).
 *
 * `<UserTypeBadge>` renders the coloured pill on the user detail card. It
 * takes the runtime catalog so the label is whatever the tenant named the
 * type; only the tone is a fixed per-category map.
 *
 * There are deliberately NO exported lists of type codes here. Types are
 * runtime data: which types exist and which need a supervisor are read off the
 * catalog rows (`parent_type_code`), and what a type may do follows from its
 * `category_code`. A hardcoded list is what stopped an operator assigning a
 * type they had just created.
 *
 * No client interactivity here, so both server and client components can
 * import it.
 */
import { Badge } from "@/components/ui/badge";
import type { UserType, UserTypeCatalog } from "@/lib/api-types";
import { userTypeLabel } from "@/lib/user-type-catalog";

/**
 * Badge tone per category. Colour tracks the CATEGORY, not the type, because
 * types are runtime data — a tenant's own Business type reads the same as the
 * system ones instead of falling back to a neutral grey.
 */
const CATEGORY_TONE: Record<string, "neutral" | "accent" | "warning"> = {
  consumer: "neutral",
  retail: "accent",
  business: "warning",
};

/**
 * The coloured pill for a user type.
 *
 * The label comes from the catalog rather than a hardcoded map, so a type an
 * operator created shows its real name instead of its raw code. Without a
 * catalog (or for a code the catalog no longer carries) it degrades to the
 * code itself in the neutral tone.
 *
 * @param type The stored user-type code.
 * @param catalog The tenant's user-type catalog, fetched server-side.
 */
export function UserTypeBadge({
  type,
  catalog,
}: {
  type: UserType;
  catalog?: UserTypeCatalog | null;
}) {
  const option = catalog?.types.find((t) => t.code === type);
  const tone = option ? (CATEGORY_TONE[option.category_code] ?? "neutral") : "neutral";
  return <Badge tone={tone}>{userTypeLabel(catalog, type)}</Badge>;
}
