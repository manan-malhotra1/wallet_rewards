/**
 * Friendly labels + one-line summaries for money operations (Epic 18). Shared
 * by the money-approvals table and its detail drawer so a raw operation code
 * like `withdraw_user` always reads as "Withdraw from user" and never leaks.
 */
import { accountTypeLabel } from "@/lib/account-type-label";
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

/** "ZAR 150.00" from a payload's currency + amount; just "150.00" if no currency. */
function moneyText(payload: Record<string, unknown>): string {
  const amount = formatCap(field(payload, "amount"));
  const currency = field(payload, "currency");
  return currency ? `${currency} ${amount}` : amount;
}

/**
 * A human one-liner describing what a money operation would do — shown in the
 * table's summary column. Reads as a sentence ("Add 500.00 to Cash float via
 * Steward Bank"), with amounts at 2 decimals, wallet type keys translated to
 * friendly labels, and account UUIDs shortened only as a last resort. Never
 * throws on an unexpected payload shape.
 */
export function moneyOperationSummary(op: MoneyOperation): string {
  const p = op.payload;
  switch (op.operation) {
    case "fund_user": {
      const money = moneyText(p);
      // Prefer the resolved user name; fall back to the raw identifier.
      const target = op.subject_name ?? field(p, "identifier_value") ?? "—";
      return `Fund ${target} with ${money}`;
    }
    case "withdraw_user": {
      const target = op.subject_name ?? field(p, "identifier_value") ?? "—";
      if (p.withdraw_all === true) return `Withdraw all funds from ${target}`;
      return `Withdraw ${moneyText(p)} from ${target}`;
    }
    case "adjust_system_wallet": {
      const raw = Number(field(p, "amount") ?? 0);
      const amount = formatCap(Math.abs(raw));
      // Prefer resolved wallet names (translating raw type keys like
      // `system_cash_inflow` to their labels); shortened UUIDs only as a
      // last resort.
      const accountId = field(p, "account_id");
      const account = op.account_name
        ? accountTypeLabel(op.account_name)
        : accountId
          ? shortId(accountId)
          : "wallet";
      const move =
        raw >= 0 ? `Add ${amount} to ${account}` : `Deduct ${amount} from ${account}`;
      const mirror = op.bank_mirror_name ? accountTypeLabel(op.bank_mirror_name) : null;
      return mirror ? `${move} via ${mirror}` : move;
    }
    case "create_bank_mirror": {
      const name = field(p, "name") ?? "—";
      const currency = field(p, "currency") ?? "";
      return `New bank mirror “${name}” (${currency})`;
    }
    default:
      return "—";
  }
}
