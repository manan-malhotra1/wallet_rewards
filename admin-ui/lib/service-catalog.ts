/**
 * Pure helpers for the base/derived services catalog.
 *
 * These live outside the `"use client"` components that use them for two
 * reasons: a client module that exports non-components defeats Fast Refresh
 * (Next.js falls back to a full reload, which surfaced as an intermittent
 * error-boundary trip on the Services page), and pure functions belong under
 * `lib/` where the coverage gate applies.
 */
import type { Service, ServiceReadiness } from "@/lib/api-types";

/** The three prerequisites a service needs to transact, in fix order. */
export const PREREQUISITES = ["pricing", "limits", "role"] as const;

export type Prerequisite = (typeof PREREQUISITES)[number];

/**
 * Order rows as base-then-its-derived-children, each group alphabetical.
 *
 * Derived services whose base is missing from the list (soft-deleted, or
 * filtered out by a status query) are kept at the end rather than dropped —
 * they still exist and still transact, so hiding them would be worse than
 * showing them ungrouped.
 */
export function groupServices(services: Service[]): Service[] {
  const byName = (a: Service, b: Service) =>
    a.display_name.localeCompare(b.display_name);
  const bases = services.filter((s) => s.kind === "base").sort(byName);
  const derived = services.filter((s) => s.kind === "derived");
  const baseCodes = new Set(bases.map((b) => b.code));

  const ordered: Service[] = [];
  for (const base of bases) {
    ordered.push(base);
    ordered.push(
      ...derived.filter((d) => d.base_service_code === base.code).sort(byName),
    );
  }
  ordered.push(
    ...derived
      .filter((d) => !d.base_service_code || !baseCodes.has(d.base_service_code))
      .sort(byName),
  );
  return ordered;
}

/**
 * The bases a new derived service may point at: server-marked `derivable` and
 * currently active. `derivable` is computed by the backend from its service
 * registry — deliberately not re-derived here, because the rule excludes
 * specific bases (`change_pin`) and a TypeScript copy would drift.
 */
export function derivableBases(services: Service[]): Service[] {
  return services
    .filter((s) => s.derivable && s.status === "active")
    .sort((a, b) => a.display_name.localeCompare(b.display_name));
}

/**
 * Which values a derived service may pick on one policy dimension.
 *
 * The backend enforces narrowing-only: a derived service may never permit a
 * user type or channel its base excludes. So when the base carries an
 * allow-list, that list IS the option set; when the base is unrestricted
 * (`null`), everything is on the table.
 */
export function allowedOptions(
  baseValues: string[] | null,
  all: readonly string[],
): readonly string[] {
  return baseValues === null ? all : baseValues;
}

/**
 * Translate a chip selection into the value the API expects for one dimension.
 *
 * The empty selection is genuinely ambiguous and the two cases are NOT
 * interchangeable:
 *  - base unrestricted → `null`, meaning "inherit the base's openness".
 *  - base restricted → there is no safe reading. `null` would be WIDER than
 *    the base, and the backend also rejects `[]` here (its narrowing check
 *    treats empty and null alike), so an empty selection cannot be submitted
 *    at all. The form blocks it rather than letting the admin meet it as a 422.
 */
export function policyValue(
  selected: string[],
  baseValues: string[] | null,
): string[] | null {
  if (selected.length > 0) return selected;
  return baseValues === null ? null : [];
}

/**
 * Which prerequisites this service is missing, fix-order first.
 *
 * A `null` readiness means the caller didn't ask for it (create/patch
 * responses), which is NOT the same as "nothing missing" — it returns empty so
 * the notice stays hidden rather than claiming a service is broken on no
 * evidence.
 */
export function missingPrerequisites(
  readiness: ServiceReadiness | null,
): Prerequisite[] {
  if (!readiness) return [];
  return PREREQUISITES.filter((key) => !readiness[key]);
}
