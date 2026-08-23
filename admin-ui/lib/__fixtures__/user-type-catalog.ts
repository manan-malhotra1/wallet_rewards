/**
 * A user-type catalog fixture mirroring the seeded system types, for component
 * tests that need to render a type picker or resolve a type label.
 *
 * Kept in one place so a change to the catalog shape is a single edit rather
 * than a sweep across every dialog test.
 */
import type { UserTypeCatalog } from "@/lib/api-types";

/** The three fixed categories and the five system types seeded per tenant. */
export const SEED_USER_TYPE_CATALOG: UserTypeCatalog = {
  categories: [
    { code: "consumer", label: "Consumers", display_order: 1, supports_hierarchy: false },
    { code: "retail", label: "Retail", display_order: 2, supports_hierarchy: true },
    { code: "business", label: "Business", display_order: 3, supports_hierarchy: true },
  ],
  types: [
    {
      code: "consumer",
      label: "Consumer",
      category_code: "consumer",
      parent_type_code: null,
      is_system: true,
      status: "active",
      requires_merchant_profile: false,
    },
    {
      code: "super_agent",
      label: "Super agent",
      category_code: "retail",
      parent_type_code: null,
      is_system: true,
      status: "active",
      requires_merchant_profile: false,
    },
    {
      code: "agent",
      label: "Agent",
      category_code: "retail",
      parent_type_code: "super_agent",
      is_system: true,
      status: "active",
      requires_merchant_profile: false,
    },
    {
      code: "head_merchant",
      label: "Head merchant",
      category_code: "business",
      parent_type_code: null,
      is_system: true,
      status: "active",
      requires_merchant_profile: true,
    },
    {
      code: "merchant",
      label: "Merchant",
      category_code: "business",
      parent_type_code: "head_merchant",
      is_system: true,
      status: "active",
      requires_merchant_profile: true,
    },
  ],
};
