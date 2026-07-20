/**
 * Config scope-key helpers (Epic 25 Pass 2, Task A).
 *
 * A config's SCOPE is the tuple of dimensions that make it unique for its type
 * — mirroring the backend keys. `configScopeKey` builds one normalized string
 * key from EITHER a live config row / group OR a change-request payload, so a
 * row can be matched against the open update/delete requests that target it.
 *
 * Scope tuples (backend):
 *   pricing / limit  → (transaction_type, account_type, currency, user_type)
 *   commission       → (transaction_type, currency, user_type)
 *   wallet_limit     → (currency, user_type)
 *   tax              → (currency)
 *   step_up          → (transaction_type, currency)
 */
import type { ConfigChangeRequest, ConfigType } from "@/lib/api-types";

type Row = Record<string, unknown>;

/** Normalize a currency to its upper-cased code, or "—" when absent. */
function normCurrency(value: unknown): string {
  return value == null || value === "" ? "—" : String(value).toUpperCase();
}

/**
 * Normalize a user_type. Null / undefined / "all" all collapse to "all" so a
 * row that applies to every user type keys the same as its all-types payload.
 */
function normUserType(value: unknown): string {
  return value == null || value === "" || value === "all" ? "all" : String(value);
}

/** Normalize a plain scope field (service / account code) to a stable token. */
function normField(value: unknown): string {
  return value == null || value === "" ? "—" : String(value);
}

/**
 * The scope-bearing object for any config shape. Band configs (pricing /
 * commission) wrap their scope fields inside each band, so a multi-band group
 * or `{ bands: [...] }` payload takes its scope from the first band; every
 * other shape (flat live row, flat payload) carries the fields at top level.
 */
function scopeSource(obj: Row): Row {
  const bands = (obj as { bands?: unknown }).bands;
  if (Array.isArray(bands) && bands.length > 0) return bands[0] as Row;
  return obj;
}

/**
 * Build a normalized scope key for a config of `configType` from either a live
 * config row / group or a change-request payload.
 *
 * @param configType Which config domain the object belongs to.
 * @param obj A live row, a grouped config (`{ bands, ... }`), or a request
 *   payload. Multi-band shapes are keyed off `bands[0]`.
 * @returns A stable key prefixed with the config type (e.g.
 *   `pricing|cash_in|financial_wallet|ZAR|all`), safe to mix across types in a
 *   single set.
 */
export function configScopeKey(configType: ConfigType, obj: object): string {
  const src = scopeSource(obj as Row);
  const currency = normCurrency(src.currency);
  const userType = normUserType(src.user_type);
  switch (configType) {
    case "tax":
      return `tax|${currency}`;
    case "step_up":
      return `step_up|${normField(src.transaction_type)}|${currency}`;
    case "wallet_limit":
      return `wallet_limit|${currency}|${userType}`;
    case "commission":
      return `commission|${normField(src.transaction_type)}|${currency}|${userType}`;
    case "pricing":
    case "limit":
      return `${configType}|${normField(src.transaction_type)}|${normField(
        src.account_type,
      )}|${currency}|${userType}`;
  }
}

/**
 * The set of scope keys that have an OPEN update/delete request for one config
 * type — the "Active · change proposed" indicator source for a table.
 *
 * An UPDATE carries its scope in the request payload. A DELETE carries no
 * payload (only `target_config_id`), so its scope is recovered by matching the
 * target id back to a live config row. A pending CREATE is excluded: it has no
 * matching live row and belongs in the open-requests area, not a row status.
 *
 * @param configType Which config domain to build the set for.
 * @param openRequests Already-filtered open (PENDING / CHANGES_REQUESTED)
 *   requests; may include other config types (they are skipped here).
 * @param liveConfigs Flat live config rows (each with an `id`) used to resolve
 *   a delete's target back to a scope.
 * @returns Scope keys (from {@link configScopeKey}) with a proposed change.
 */
export function changeProposedScopeKeys(
  configType: ConfigType,
  openRequests: ConfigChangeRequest[],
  liveConfigs: ReadonlyArray<{ id: string }>,
): Set<string> {
  const byId = new Map(liveConfigs.map((cfg) => [cfg.id, cfg]));
  const keys = new Set<string>();
  for (const req of openRequests) {
    if (req.config_type !== configType) continue;
    if (req.operation === "update" && req.payload) {
      keys.add(configScopeKey(configType, req.payload));
    } else if (req.operation === "delete" && req.target_config_id) {
      const row = byId.get(req.target_config_id);
      if (row) keys.add(configScopeKey(configType, row));
    }
  }
  return keys;
}
