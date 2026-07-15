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
import { serviceLabel } from "@/lib/service-label";
import { formatAmount } from "@/lib/utils";

type Row = Record<string, unknown>;

/** Config types whose payloads carry a multi-band schedule. */
const BAND_TYPES: ReadonlySet<ConfigType> = new Set(["pricing", "commission"]);

/** Keys never shown — internal identifiers + timestamps. */
const HIDDEN_KEYS = new Set(["tenant_id", "id", "created_at", "updated_at"]);

/** Money-valued keys formatted with thousands separators + 2 decimals. */
const MONEY_KEYS = new Set([
  "amount_from",
  "amount_to",
  "fixed_fee",
  "fee_cap",
  "fixed_commission",
  "commission_cap",
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

const ACCOUNT_TYPE_LABEL: Record<string, string> = {
  financial_wallet: "Wallet",
  points_account: "Points",
};

/** Title-case a snake_case key when no explicit label exists. */
function humanize(key: string): string {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Format a decimal-string rate (e.g. "0.15") as a percentage. */
function pct(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : String(value);
}

/** Format one scalar field value for display. */
function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (key.endsWith("_pct")) return pct(value);
  if (key.endsWith("_value_cap") || MONEY_KEYS.has(key)) {
    return formatAmount(String(value), { fractionDigits: 2 });
  }
  return String(value);
}

/** Render the slab band as "from–to", "≥from", "≤to", or "all". */
function bandLabel(from: unknown, to: unknown): string {
  const f = from === null || from === undefined || from === "" ? null : String(from);
  const t = to === null || to === undefined || to === "" ? null : String(to);
  if (f && t) return `${formatAmount(f)}–${formatAmount(t)}`;
  if (f) return `≥ ${formatAmount(f)}`;
  if (t) return `≤ ${formatAmount(t)}`;
  return "all";
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
function BandsTable({ configType, bands }: { configType: ConfigType; bands: Row[] }) {
  const isPricing = configType === "pricing";
  const fixedKey = isPricing ? "fixed_fee" : "fixed_commission";
  const varKey = isPricing ? "variable_fee_pct" : "variable_commission_pct";
  const capKey = isPricing ? "fee_cap" : "commission_cap";
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
                {formatAmount(String(band[fixedKey] ?? "0"), { fractionDigits: 2 })}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {pct(band[varKey] ?? "0")}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {band[capKey] === null ||
                band[capKey] === undefined ||
                band[capKey] === ""
                  ? "—"
                  : formatAmount(String(band[capKey]), { fractionDigits: 2 })}
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
        <Field key={key} label={FIELD_LABELS[key] ?? humanize(key)}>
          {key === "transaction_type" ? (
            <Badge variant="info">
              {serviceLabel(String(value), serviceNames)}
            </Badge>
          ) : key === "user_type" ? (
            value ? (
              <UserTypeBadge type={value as UserType} />
            ) : (
              <span className="text-muted-foreground">All types</span>
            )
          ) : key === "account_type" ? (
            ACCOUNT_TYPE_LABEL[String(value)] ?? String(value)
          ) : (
            formatValue(key, value)
          )}
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
    const rawBands = (data as Row).bands;
    const bands: Row[] = Array.isArray(rawBands) ? (rawBands as Row[]) : [data];
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
        <BandsTable configType={configType} bands={bands} />
      </div>
    );
  }

  return <FlatFields data={data} serviceNames={serviceNames} />;
}
