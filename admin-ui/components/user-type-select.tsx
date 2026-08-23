/**
 * <UserTypeSelect> — the cascading category → user-type picker.
 *
 * Replaces the flat user-type dropdown everywhere a config is scoped to a type.
 * The operator narrows to a kind of customer first, which keeps the second list
 * short as tenants add their own types.
 *
 * Editing an existing config passes the stored code as `value`; the category is
 * derived from it so the control opens already narrowed.
 */
"use client";

import * as React from "react";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { UserTypeCatalog } from "@/lib/api-types";
import { groupTypesByCategory } from "@/lib/user-type-catalog";

/**
 * Radix `<Select>` cannot hold the empty string as an item value, so the two
 * "no narrowing" choices carry explicit sentinels that never reach the wire.
 */
const ANY_CATEGORY = "__all__";
const ANY_TYPE = "__any__";

/**
 * A category dropdown paired with a type dropdown filtered to it.
 *
 * @param catalog The tenant's user-type catalog, fetched server-side.
 * @param value The stored type code, or null for "not chosen".
 * @param onChange Fires with the chosen code, or null when the category is
 *   cleared or the type is reset to "Any".
 * @param disabled Locks both dropdowns (scope-locked edit / revise).
 * @param idPrefix Disambiguates the two labels' `htmlFor` when more than one
 *   picker is on a page.
 * @param allowAny Whether "All customers" / "Any" are offered. True when the
 *   picker scopes a CONFIG (a null type means "everyone"); false when it
 *   assigns a type to a PERSON, where there is no such thing as "any type".
 */
export function UserTypeSelect({
  catalog,
  value,
  onChange,
  disabled = false,
  idPrefix = "user-type",
  allowAny = true,
}: {
  catalog: UserTypeCatalog;
  value: string | null;
  onChange: (code: string | null) => void;
  disabled?: boolean;
  idPrefix?: string;
  allowAny?: boolean;
}) {
  const groups = React.useMemo(() => groupTypesByCategory(catalog), [catalog]);
  // Radix shows the placeholder for an empty value, which is what "nothing
  // chosen yet" looks like once the "All customers" escape hatch is gone.
  const noCategory = allowAny ? ANY_CATEGORY : "";
  const derivedCategory =
    catalog.types.find((t) => t.code === value)?.category_code ?? noCategory;
  const [category, setCategory] = React.useState(derivedCategory);

  // Keep the category in step when the parent swaps `value` (e.g. editing a
  // different row without remounting). Adjusted during render rather than in
  // an effect: an effect would paint one frame with the old category first.
  //
  // Only a NON-NULL value re-narrows. Changing the category itself reports
  // `onChange(null)`, so a parent that stores the type would otherwise feed
  // back "no type" and this guard would immediately undo the category the
  // operator just picked — leaving the type dropdown permanently disabled.
  const [lastValue, setLastValue] = React.useState(value);
  if (value !== lastValue) {
    setLastValue(value);
    if (value !== null) setCategory(derivedCategory);
  }

  const typesInCategory =
    groups.find((g) => g.category.code === category)?.types ?? [];
  const categoryId = `${idPrefix}-category`;
  const typeId = `${idPrefix}-type`;

  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <Label htmlFor={categoryId}>Category</Label>
        <Select
          value={category}
          disabled={disabled}
          onValueChange={(next) => {
            setCategory(next);
            // The old type may not belong to the new category, so drop it
            // rather than submit a type/category pair that cannot exist.
            onChange(null);
          }}
        >
          <SelectTrigger id={categoryId} aria-label="Category">
            <SelectValue placeholder="Select a category" />
          </SelectTrigger>
          <SelectContent>
            {allowAny && <SelectItem value={ANY_CATEGORY}>All customers</SelectItem>}
            {groups.map((g) => (
              <SelectItem key={g.category.code} value={g.category.code}>
                {g.category.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label htmlFor={typeId}>User type</Label>
        <Select
          value={value ?? (allowAny ? ANY_TYPE : "")}
          disabled={disabled || category === noCategory}
          onValueChange={(next) => onChange(next === ANY_TYPE ? null : next)}
        >
          <SelectTrigger id={typeId} aria-label="User type">
            <SelectValue placeholder="Select a type" />
          </SelectTrigger>
          <SelectContent>
            {allowAny && <SelectItem value={ANY_TYPE}>Any</SelectItem>}
            {typesInCategory.map((t) => (
              <SelectItem key={t.code} value={t.code}>
                {/* Children sit under their parent; the indent is the
                    two-level hierarchy made visible in a flat list. */}
                {t.parent_type_code ? `  ${t.label}` : t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
