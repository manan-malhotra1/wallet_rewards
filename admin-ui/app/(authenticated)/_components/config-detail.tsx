/**
 * Shared read-only config presentation (Epic 25 / Task 6).
 *
 * Renders a config — either a LIVE row or a proposed-change payload — as a
 * labeled field list in the app's sans typography (no `font-mono` except the
 * raw-id fallback). For pricing/commission it accepts a single row OR a
 * `{ bands: [...] }` payload: the shared scope renders once, then a compact
 * bands table. For tax/limit/wallet_limit it renders the flat fields.
 *
 * Reused by the native "View" drawers and the config-request approval drawer,
 * which unifies "view a live config" and "review a proposed change".
 */
import { UserTypeBadge } from "@/app/(authenticated)/users/_components/user-type-badge";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import type { ConfigType, UserType } from "@/lib/api-types";
import { payoutDestinationLabel } from "@/lib/commission-batch";
import { serviceLabel } from "@/lib/service-label";
import { formatAmount } from "@/lib/utils";

export type Row = Record<string, unknown>;

/** Config types whose payloads carry a multi-band schedule. */
export const BAND_TYPES: ReadonlySet<ConfigType> = new Set([
  "pricing",
  "commission",
]);

/** Keys never shown — internal identifiers + timestamps. */
export const HIDDEN_KEYS = new Set(["tenant_id", "id", "created_at", "updated_at"]);

/** Money-valued keys formatted with thousands separators + 2 decimals. */
const MONEY_KEYS = new Set([
  "amount_from",
  "amount_to",
  "fixed_fee",
  "fee_cap",
  "fixed_commission",
  "commission_cap",
  // The parent's terms are money too, and must read the same way as the
  // child's — "0.50", not a raw "0.5" beside a formatted sibling.
  "parent_fixed_commission",
  "parent_commission_cap",
  "min_amount",
  "max_amount",
  "max_balance",
]);

/** Human labels for the flat (tax/limit) fields. */
const FIELD_LABELS: Record<string, string> = {
  transaction_type: "Service",
  account_type: "Account type",
  currency: "Currency",
  user_type: "User type",
  fee_inclusive: "Fee inclusive",
  fee_tax_pct: "Fee tax",
  commission_tax_pct: "Commission tax",
  fee_tax_inclusive: "Fee tax inclusive",
  commission_tax_inclusive: "Commission tax inclusive",
  payout_destination: "Pays into",
  parent_fixed_commission: "Parent fixed",
  parent_variable_commission_pct: "Parent variable",
  parent_commission_cap: "Parent cap",
  min_amount: "Min amount",
  max_amount: "Max amount",
  max_balance: "Max balance",
  daily_count_cap: "Daily count cap",
  daily_value_cap: "Daily value cap",
  weekly_count_cap: "Weekly count cap",
  weekly_value_cap: "Weekly value cap",
  monthly_count_cap: "Monthly count cap",
  monthly_value_cap: "Monthly value cap",
  send_daily_count_cap: "Send · daily count",
  send_daily_value_cap: "Send · daily value",
  send_weekly_count_cap: "Send · weekly count",
  send_weekly_value_cap: "Send · weekly value",
  send_monthly_count_cap: "Send · monthly count",
  send_monthly_value_cap: "Send · monthly value",
  receive_daily_count_cap: "Receive · daily count",
  receive_daily_value_cap: "Receive · daily value",
  receive_weekly_count_cap: "Receive · weekly count",
  receive_weekly_value_cap: "Receive · weekly value",
  receive_monthly_count_cap: "Receive · monthly count",
  receive_monthly_value_cap: "Receive · monthly value",
};

export const ACCOUNT_TYPE_LABEL: Record<string, string> = {
  financial_wallet: "Wallet",
  points_account: "Points",
};

/** Title-case a snake_case key when no explicit label exists. */
export function humanize(key: string): string {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Human label for any config field (explicit map, else title-cased key). */
export function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? humanize(key);
}

/** Format a decimal-string rate (e.g. "0.15") as a percentage. */
export function pct(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : String(value);
}

/**
 * Format one scalar field value for display (booleans, percentages, money,
 * plain strings). The single source of truth for config value formatting —
 * both the detail view and the side-by-side compare share it so displayed
 * values (and thus diff detection) stay consistent.
 */
export function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (key.endsWith("_pct")) return pct(value);
  if (key.endsWith("_value_cap") || MONEY_KEYS.has(key)) {
    return formatAmount(String(value), { fractionDigits: 2 });
  }
  return String(value);
}

/** The fixed / variable-% / cap payload keys for a band config type. */
export function bandFieldKeys(configType: ConfigType): {
  fixedKey: string;
  varKey: string;
  capKey: string;
} {
  const isPricing = configType === "pricing";
  return {
    fixedKey: isPricing ? "fixed_fee" : "fixed_commission",
    varKey: isPricing ? "variable_fee_pct" : "variable_commission_pct",
    capKey: isPricing ? "fee_cap" : "commission_cap",
  };
}

/**
 * Extract the band rows from a config payload. Band types wrap their bands in
 * a `{ bands: [...] }` payload (or a single flat row for legacy data); flat
 * types have no bands and yield an empty list.
 */
export function bandsOf(configType: ConfigType, data: Row | null): Row[] {
  if (!data || !BAND_TYPES.has(configType)) return [];
  const rawBands = (data as Row).bands;
  return Array.isArray(rawBands) ? (rawBands as Row[]) : [data];
}

/** Render the slab band as "from–to", "≥from", "≤to", or "all". */
export function bandLabel(from: unknown, to: unknown): string {
  const f = from === null || from === undefined || from === "" ? null : String(from);
  const t = to === null || to === undefined || to === "" ? null : String(to);
  if (f && t) return `${formatAmount(f)}–${formatAmount(t)}`;
  if (f) return `≥ ${formatAmount(f)}`;
  if (t) return `≤ ${formatAmount(t)}`;
  return "all";
}

/**
 * Render one flat field's value as display-ready JSX: a service badge for
 * `transaction_type`, a user-type badge (or "All types") for `user_type`, the
 * friendly account-type label for `account_type`, else the formatted scalar.
 * Shared by the detail view and the compare so both render fields identically.
 */
export function renderFieldValue(
  key: string,
  value: unknown,
  serviceNames?: Record<string, string>,
): React.ReactNode {
  if (key === "transaction_type") {
    return (
      <Badge variant="info">{serviceLabel(String(value), serviceNames)}</Badge>
    );
  }
  if (key === "user_type") {
    return value ? (
      <UserTypeBadge type={value as UserType} />
    ) : (
      <span className="text-muted-foreground">All types</span>
    );
  }
  if (key === "account_type") {
    return ACCOUNT_TYPE_LABEL[String(value)] ?? String(value);
  }
  return formatValue(key, value);
}

/** One labeled definition-list row (sans typography). */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm text-foreground">{children}</dd>
    </>
  );
}

/** Render the shared scope common to every band of a pricing/commission schedule. */
function ScopeFields({
  configType,
  scope,
  serviceNames,
}: {
  configType: ConfigType;
  scope: Row;
  serviceNames?: Record<string, string>;
}) {
  const userType = scope.user_type as UserType | null | undefined;
  const code =
    scope.transaction_type == null ? null : String(scope.transaction_type);
  return (
    <dl className="grid grid-cols-[minmax(0,9rem)_1fr] gap-x-3 gap-y-1.5">
      <Field label="Service">
        <Badge variant="info">
          {code ? serviceLabel(code, serviceNames) : "—"}
        </Badge>
      </Field>
      {scope.account_type !== undefined && (
        <Field label="Account type">
          {ACCOUNT_TYPE_LABEL[String(scope.account_type)] ??
            String(scope.account_type)}
        </Field>
      )}
      <Field label="Currency">{String(scope.currency ?? "—")}</Field>
      <Field label="User type">
        {userType ? (
          <UserTypeBadge type={userType} />
        ) : (
          <span className="text-muted-foreground">All types</span>
        )}
      </Field>
      {configType === "pricing" && (
        <Field label="Fee inclusive">{scope.fee_inclusive ? "Yes" : "No"}</Field>
      )}
    </dl>
  );
}

/** Render the bands table (from/to/fixed/variable%/cap). */
/**
 * Commission-only terms a checker approves but could not previously see: where
 * the commission pays, and what the earner's supervisor gets.
 *
 * Rendered as its own block rather than extra band columns. The create dialog
 * treats these as SCOPE-level (one set for the whole schedule) even though the
 * backend stores them per row, so columns would wrongly imply they can differ
 * between bands. If a payload ever does disagree across bands the mismatch is
 * surfaced rather than silently showing the first band's value.
 */
function CommissionTerms({ bands }: { bands: Row[] }) {
  const first = bands[0] ?? {};
  const destination = String(first.payout_destination ?? "main_wallet");

  const term = (key: string) => String(first[key] ?? "0");
  const inconsistent = bands.some(
    (b) =>
      String(b.payout_destination ?? "main_wallet") !== destination ||
      String(b.parent_fixed_commission ?? "0") !== term("parent_fixed_commission") ||
      String(b.parent_variable_commission_pct ?? "0") !==
        term("parent_variable_commission_pct"),
  );

  return (
    <div className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Pays into
        </span>
        <span
          className={
            "rounded px-1.5 py-0.5 text-xs font-medium " +
            (destination === "commission_wallet"
              ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
              : "bg-muted text-foreground")
          }
        >
          {payoutDestinationLabel(destination)}
        </span>
        {destination === "commission_wallet" ? (
          <span className="text-xs text-muted-foreground">
            held for review, not spendable on payout
          </span>
        ) : null}
      </div>

      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Parent commission
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Paid to the earner&apos;s supervisor, as a percentage of the
          transaction amount.
        </p>
        <dl className="mt-2 grid grid-cols-3 gap-3 text-sm">
          {[
            ["Fixed", "parent_fixed_commission"],
            ["Variable %", "parent_variable_commission_pct"],
            ["Cap", "parent_commission_cap"],
          ].map(([label, key]) => (
            <div key={key}>
              <dt className="text-xs text-muted-foreground">{label}</dt>
              {/* Zero renders as an explicit "0", never blank: stating zero is
                  a decision the maker is required to make, and a blank cell
                  would erase the difference between "stated zero" and "not
                  set". A cap is genuinely optional, so it may read "—". */}
              <dd className="tabular-nums">
                {key === "parent_commission_cap"
                  ? formatValue("commission_cap", first[key])
                  : formatValue(key, first[key] ?? "0")}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      {inconsistent ? (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          These terms differ between bands in this payload — open each band
          before approving.
        </p>
      ) : null}
    </div>
  );
}

function BandsTable({ configType, bands }: { configType: ConfigType; bands: Row[] }) {
  const { fixedKey, varKey, capKey } = bandFieldKeys(configType);
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Band</TableHeaderCell>
            <TableHeaderCell className="text-right">Fixed</TableHeaderCell>
            <TableHeaderCell className="text-right">Variable %</TableHeaderCell>
            <TableHeaderCell className="text-right">Cap</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {bands.map((band, i) => (
            <TableRow key={i}>
              <TableCell>{bandLabel(band.amount_from, band.amount_to)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {formatValue(fixedKey, band[fixedKey] ?? "0")}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatValue(varKey, band[varKey] ?? "0")}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatValue(capKey, band[capKey])}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Render the flat fields of a tax/limit/wallet_limit config. */
function FlatFields({
  data,
  serviceNames,
}: {
  data: Row;
  serviceNames?: Record<string, string>;
}) {
  const entries = Object.entries(data).filter(([key]) => !HIDDEN_KEYS.has(key));
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No fields.</p>;
  }
  return (
    <dl className="grid grid-cols-[minmax(0,11rem)_1fr] gap-x-3 gap-y-1.5">
      {entries.map(([key, value]) => (
        <Field key={key} label={fieldLabel(key)}>
          {renderFieldValue(key, value, serviceNames)}
        </Field>
      ))}
    </dl>
  );
}

/**
 * Read-only view of a config or a proposed change.
 *
 * @param configType Which config domain the data belongs to.
 * @param data A live config row, or a proposed-change payload. For
 *   pricing/commission this may be a single row or a `{ bands: [...] }` object.
 * @param serviceNames Optional `{ code: display_name }` map so a
 *   `transaction_type` renders as its friendly service name rather than the
 *   raw code. Falls back to `transactionTypeLabel` when absent or unmapped.
 */
export function ConfigDetail({
  configType,
  data,
  serviceNames,
}: {
  configType: ConfigType;
  data: Row | null;
  serviceNames?: Record<string, string>;
}) {
  if (!data) {
    return <p className="text-sm text-muted-foreground">No payload.</p>;
  }

  if (BAND_TYPES.has(configType)) {
    const bands = bandsOf(configType, data);
    if (bands.length === 0) {
      return <p className="text-sm text-muted-foreground">No bands.</p>;
    }
    return (
      <div className="space-y-4">
        <ScopeFields
          configType={configType}
          scope={bands[0]}
          serviceNames={serviceNames}
        />
        {configType === "commission" ? <CommissionTerms bands={bands} /> : null}
        <BandsTable configType={configType} bands={bands} />
      </div>
    );
  }

  return <FlatFields data={data} serviceNames={serviceNames} />;
}
