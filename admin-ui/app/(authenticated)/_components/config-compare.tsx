/**
 * <ConfigCompare> — side-by-side diff of two config payloads (Epic 25 Pass 2,
 * Task B). Renders two labeled columns for a given `configType` and highlights
 * what changed between them:
 *   - flat types (tax / limit / wallet_limit): field-by-field, a differing
 *     field highlighted, unchanged fields muted;
 *   - band types (pricing / commission): the shared scope compared field-by-
 *     field, then bands aligned by amount range and marked added / removed /
 *     changed / unchanged.
 *
 * Every difference carries a text cue (both values shown, plus an
 * Added/Removed/Changed label for bands) so the diff never relies on colour
 * alone (frontend-admin accessibility rule). Formatting + field labels are
 * imported from `config-detail` — never duplicated here.
 */
import { Minus, Plus, RefreshCw } from "lucide-react";

import {
  BAND_TYPES,
  HIDDEN_KEYS,
  bandFieldKeys,
  bandLabel,
  bandsOf,
  fieldLabel,
  formatValue,
  renderFieldValue,
} from "@/app/(authenticated)/_components/config-detail";
import type { Row } from "@/app/(authenticated)/_components/config-detail";
import { cn } from "@/lib/utils";
import type { ConfigType } from "@/lib/api-types";

/** One side of the comparison: a column label and its payload (or null). */
export interface ComparePayload {
  label: string;
  data: Row | null;
}

/**
 * The commission-only fields that must count toward "did this band change?".
 * Harmless for pricing: those payloads never carry these keys, so both sides
 * read undefined and compare equal.
 */
const COMMISSION_TERM_KEYS = [
  "payout_destination",
  "parent_fixed_commission",
  "parent_variable_commission_pct",
  "parent_commission_cap",
] as const;

/** Per-band diff verdict when aligning two schedules. */
type BandStatus = "added" | "removed" | "changed" | "unchanged";

/** The scope fields compared for a band config's shared header. */
const PRICING_SCOPE_KEYS = [
  "transaction_type",
  "account_type",
  "currency",
  "user_type",
  "fee_inclusive",
];
const COMMISSION_SCOPE_KEYS = [
  "transaction_type",
  "currency",
  "user_type",
];

/** Two values are "the same" when they render identically for this field. */
function sameValue(key: string, a: unknown, b: unknown): boolean {
  return formatValue(key, a) === formatValue(key, b);
}

/** Column-header row naming each side of the comparison. */
function CompareHeader({ left, right }: { left: string; right: string }) {
  return (
    <>
      <div />
      <div className="text-xs font-semibold text-muted-foreground">{left}</div>
      <div className="text-xs font-semibold text-muted-foreground">{right}</div>
    </>
  );
}

/**
 * Field-by-field comparison of two flat objects over `keys`. A field whose two
 * values render differently gets an amber row with both values bold; unchanged
 * fields stay muted. Rendered as a 3-column grid (label · left · right).
 */
function FlatCompare({
  keys,
  left,
  right,
  leftLabel,
  rightLabel,
  serviceNames,
}: {
  keys: string[];
  left: Row;
  right: Row;
  leftLabel: string;
  rightLabel: string;
  serviceNames?: Record<string, string>;
}) {
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[22rem] grid-cols-[minmax(6rem,10rem)_1fr_1fr] items-center gap-x-3 gap-y-1">
        <CompareHeader left={leftLabel} right={rightLabel} />
        {keys.map((key) => {
          const changed = !sameValue(key, left[key], right[key]);
          return (
            <div
              key={key}
              className={cn(
                "col-span-3 grid grid-cols-subgrid items-center rounded px-1 py-1",
                changed && "bg-amber-500/10",
              )}
            >
              <span className="text-xs text-muted-foreground">
                {fieldLabel(key)}
                {changed && (
                  <span className="ml-1 text-amber-600 dark:text-amber-400">
                    · changed
                  </span>
                )}
              </span>
              <span
                className={cn(
                  "text-sm",
                  changed ? "text-muted-foreground line-through" : "text-muted-foreground",
                )}
              >
                {renderFieldValue(key, left[key], serviceNames)}
              </span>
              <span
                className={cn(
                  "text-sm",
                  changed ? "font-semibold text-foreground" : "text-muted-foreground",
                )}
              >
                {renderFieldValue(key, right[key], serviceNames)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Ordered union of the non-hidden keys across two flat objects (left first). */
function unionKeys(left: Row, right: Row): string[] {
  const keys: string[] = [];
  for (const k of [...Object.keys(left), ...Object.keys(right)]) {
    if (!HIDDEN_KEYS.has(k) && !keys.includes(k)) keys.push(k);
  }
  return keys;
}

/** Numeric sort key for a band's lower bound; unbounded (null) sorts last. */
function fromSortKey(from: unknown): number {
  if (from === null || from === undefined || from === "") return Infinity;
  const n = parseFloat(String(from));
  return Number.isFinite(n) ? n : Infinity;
}

/** Stable range identity for aligning bands across two schedules. */
function rangeKey(band: Row): string {
  const norm = (v: unknown) =>
    v === null || v === undefined || v === "" ? "∞" : String(parseFloat(String(v)));
  return `${norm(band.amount_from)}|${norm(band.amount_to)}`;
}

/** The visual treatment (label, icon, colours) for a band diff verdict. */
function bandStatusStyle(status: BandStatus): {
  label: string;
  icon: React.ReactNode;
  row: string;
  badge: string;
} {
  switch (status) {
    case "added":
      return {
        label: "Added",
        icon: <Plus className="h-3 w-3" aria-hidden="true" />,
        row: "bg-emerald-500/10",
        badge: "text-emerald-700 dark:text-emerald-300",
      };
    case "removed":
      return {
        label: "Removed",
        icon: <Minus className="h-3 w-3" aria-hidden="true" />,
        row: "bg-red-500/10",
        badge: "text-red-700 dark:text-red-300",
      };
    case "changed":
      return {
        label: "Changed",
        icon: <RefreshCw className="h-3 w-3" aria-hidden="true" />,
        row: "bg-amber-500/10",
        badge: "text-amber-700 dark:text-amber-300",
      };
    case "unchanged":
      return {
        label: "Unchanged",
        icon: null,
        row: "",
        badge: "text-muted-foreground",
      };
  }
}

/** One field cell in the bands diff: old → new when changed, else a value. */
function BandCell({
  fieldKey,
  status,
  left,
  right,
}: {
  fieldKey: string;
  status: BandStatus;
  left: Row | null;
  right: Row | null;
}) {
  if (status === "removed") {
    return (
      <span className="tabular-nums text-muted-foreground line-through">
        {formatValue(fieldKey, left?.[fieldKey])}
      </span>
    );
  }
  if (status === "added") {
    return (
      <span className="tabular-nums font-medium text-foreground">
        {formatValue(fieldKey, right?.[fieldKey])}
      </span>
    );
  }
  const changed = !sameValue(fieldKey, left?.[fieldKey], right?.[fieldKey]);
  if (!changed) {
    return (
      <span className="tabular-nums text-muted-foreground">
        {formatValue(fieldKey, right?.[fieldKey])}
      </span>
    );
  }
  return (
    <span className="tabular-nums">
      <span className="text-muted-foreground line-through">
        {formatValue(fieldKey, left?.[fieldKey])}
      </span>
      <span className="px-1 text-muted-foreground">→</span>
      <span className="font-semibold text-foreground">
        {formatValue(fieldKey, right?.[fieldKey])}
      </span>
    </span>
  );
}

/**
 * Band-schedule diff: align both sides by amount range, then classify each
 * range as added / removed / changed / unchanged and render fixed / variable%
 * / cap per band with the change made explicit.
 */
function BandsCompare({
  configType,
  leftBands,
  rightBands,
}: {
  configType: ConfigType;
  leftBands: Row[];
  rightBands: Row[];
}) {
  const { fixedKey, varKey, capKey } = bandFieldKeys(configType);
  const leftMap = new Map(leftBands.map((b) => [rangeKey(b), b]));
  const rightMap = new Map(rightBands.map((b) => [rangeKey(b), b]));

  // Union of ranges, ordered by lower bound (unbounded last). A range present
  // on one side only is an add/remove; on both, compare the fee fields.
  const orderedKeys = [...new Set([...leftMap.keys(), ...rightMap.keys()])].sort(
    (a, b) => {
      const ba = leftMap.get(a) ?? rightMap.get(a)!;
      const bb = leftMap.get(b) ?? rightMap.get(b)!;
      return fromSortKey(ba.amount_from) - fromSortKey(bb.amount_from);
    },
  );

  const rows = orderedKeys.map((key) => {
    const l = leftMap.get(key) ?? null;
    const r = rightMap.get(key) ?? null;
    let status: BandStatus;
    if (!l) status = "added";
    else if (!r) status = "removed";
    else if (
      sameValue(fixedKey, l[fixedKey], r[fixedKey]) &&
      sameValue(varKey, l[varKey], r[varKey]) &&
      sameValue(capKey, l[capKey], r[capKey]) &&
      // Commission carries three more money-affecting fields. Leaving them out
      // meant a maker could change WHERE the commission pays, or what the
      // supervisor earns, and the band still rendered "unchanged" — a checker
      // would approve an edit with nothing on screen to review.
      COMMISSION_TERM_KEYS.every((k) => sameValue(k, l[k], r[k]))
    ) {
      status = "unchanged";
    } else {
      status = "changed";
    }
    const band = (r ?? l)!;
    return { key, l, r, status, band };
  });

  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="px-3 py-2 text-left font-medium">Change</th>
            <th className="px-3 py-2 text-left font-medium">Band</th>
            <th className="px-3 py-2 text-right font-medium">Fixed</th>
            <th className="px-3 py-2 text-right font-medium">Variable %</th>
            <th className="px-3 py-2 text-right font-medium">Cap</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ key, l, r, status, band }) => {
            const style = bandStatusStyle(status);
            return (
              <tr key={key} className={cn("border-b last:border-0", style.row)}>
                <td className="px-3 py-2">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 text-xs font-medium",
                      style.badge,
                    )}
                  >
                    {style.icon}
                    {style.label}
                  </span>
                </td>
                <td className="px-3 py-2">
                  {bandLabel(band.amount_from, band.amount_to)}
                </td>
                <td className="px-3 py-2 text-right">
                  <BandCell fieldKey={fixedKey} status={status} left={l} right={r} />
                </td>
                <td className="px-3 py-2 text-right">
                  <BandCell fieldKey={varKey} status={status} left={l} right={r} />
                </td>
                <td className="px-3 py-2 text-right">
                  <BandCell fieldKey={capKey} status={status} left={l} right={r} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Compare two config payloads side by side for `configType`.
 *
 * @param configType Which config domain both payloads belong to.
 * @param left The baseline side (e.g. the current active version).
 * @param right The comparison side (e.g. the proposed version).
 * @param serviceNames `{ code: display_name }` so a service code renders as its
 *   friendly name in the scope comparison.
 */
export function ConfigCompare({
  configType,
  left,
  right,
  serviceNames,
}: {
  configType: ConfigType;
  left: ComparePayload;
  right: ComparePayload;
  serviceNames?: Record<string, string>;
}) {
  if (!left.data || !right.data) {
    return (
      <p className="text-sm text-muted-foreground">
        Not enough data to compare.
      </p>
    );
  }

  if (BAND_TYPES.has(configType)) {
    const leftBands = bandsOf(configType, left.data);
    const rightBands = bandsOf(configType, right.data);
    const scopeKeys =
      configType === "pricing" ? PRICING_SCOPE_KEYS : COMMISSION_SCOPE_KEYS;
    // Scope fields live inside each band; take them from the first band.
    const leftScope = leftBands[0] ?? {};
    const rightScope = rightBands[0] ?? {};
    return (
      <div className="space-y-4">
        <FlatCompare
          keys={scopeKeys}
          left={leftScope}
          right={rightScope}
          leftLabel={left.label}
          rightLabel={right.label}
          serviceNames={serviceNames}
        />
        <BandsCompare
          configType={configType}
          leftBands={leftBands}
          rightBands={rightBands}
        />
      </div>
    );
  }

  return (
    <FlatCompare
      keys={unionKeys(left.data, right.data)}
      left={left.data}
      right={right.data}
      leftLabel={left.label}
      rightLabel={right.label}
      serviceNames={serviceNames}
    />
  );
}
