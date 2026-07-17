/**
 * Friendly labels + one-line summaries for money operations (Epic 18). Shared
 * by the money-approvals table and its detail drawer so a raw operation code
 * like `withdraw_user` always reads as "Withdraw from user" and never leaks.
 */
import type { MoneyOperation, MoneyOperationType } from "@/lib/api-types";
import { formatCap, shortId } from "@/lib/utils";

/** Human label for each treasury operation that flows through maker-checker. */
const OPERATION_LABEL: Record<MoneyOperationType, string> = {
  fund_user: "Fund user",
  withdraw_user: "Withdraw from user",
  adjust_system_wallet: "Adjust system wallet",
  create_bank_mirror: "Create bank mirror",
};

/**
 * Friendly display name for an operation code.
 *
 * @param operation Raw operation code (e.g. `withdraw_user`).
 * @returns Friendly label (e.g. `Withdraw from user`); the raw code as a
 *   defensive fallback for any future operation the UI doesn't yet know.
 */
export function moneyOperationLabel(operation: string): string {
  return OPERATION_LABEL[operation as MoneyOperationType] ?? operation;
}

/** Read a payload field as a display string, tolerating string|number|missing. */
function field(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

/**
 * A compact, human one-liner describing what a money operation would do —
 * shown in the table's summary column. Amounts render at 2 decimals; account
 * UUIDs are shortened. Never throws on an unexpected payload shape.
 */
export function moneyOperationSummary(op: MoneyOperation): string {
  const p = op.payload;
  switch (op.operation) {
    case "fund_user": {
      const amount = formatCap(field(p, "amount"));
      const currency = field(p, "currency") ?? "";
      const target = field(p, "identifier_value") ?? "—";
      return `${currency} ${amount} → ${target}`.trim();
    }
    case "withdraw_user": {
      const target = field(p, "identifier_value") ?? "—";
      const currency = field(p, "currency") ?? "";
      const amount =
        p.withdraw_all === true ? "all" : formatCap(field(p, "amount"));
      return `${currency} ${amount} ← ${target}`.trim();
    }
    case "adjust_system_wallet": {
      const raw = Number(field(p, "amount") ?? 0);
      const signed = `${raw >= 0 ? "+" : "−"}${formatCap(Math.abs(raw))}`;
      const account = field(p, "account_id");
      return `${signed} on ${account ? shortId(account) : "wallet"}`;
    }
    case "create_bank_mirror": {
      const name = field(p, "name") ?? "—";
      const currency = field(p, "currency") ?? "";
      return `${name} (${currency})`;
    }
    default:
      return "—";
  }
}
