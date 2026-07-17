"use server";

/**
 * Server actions for the mobile-simulator. Wrap backend.ts so the
 * browser never touches PINs, session tokens, or HMAC secrets.
 */
import { revalidatePath } from "next/cache";

import {
  buyAirtime,
  cashIn,
  cashOut,
  changePin,
  externalCreateUser,
  externalFund,
  externalWithdraw,
  merchantCashin,
  fireEventHttp,
  fireEventKafka,
  sendP2P,
  simulateAirtimeCallback,
  type ExternalIdentifier,
} from "@/lib/backend";
import { config, type UserKey } from "@/lib/config";
import { formatAmount } from "@/lib/format";

export type ActionResult =
  | { ok: true; message: string }
  | { ok: false; message: string; needsPin?: boolean };

/**
 * Result of a partner external-API action. Carries a friendly `message` plus the
 * raw HTTP `status` and response `raw` text so the panel can show both the
 * summary and the exact backend response (incl. a fail-closed 422 body).
 */
export type ExternalActionResult = {
  ok: boolean;
  message: string;
  status: number;
  raw: string;
};

export async function cashInAction(
  agent: UserKey,
  customer: UserKey,
  amount: string,
  pin?: string,
): Promise<ActionResult> {
  const parsed = Number(amount);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false, message: "Amount must be a positive number." };
  }
  const res = await cashIn(agent, customer, amount, pin);
  revalidatePath("/");
  if (res.ok) {
    // Surface the fee / commission / tax breakdown from the response.
    try {
      const b = JSON.parse(res.body) as {
        amount: string;
        fee: string;
        commission: string;
        tax: string;
      };
      return {
        ok: true,
        message:
          `Cashed in R ${formatAmount(b.amount, "ZAR")} to ${config.users[customer].label} — ` +
          `fee R ${formatAmount(b.fee, "ZAR")}, commission R ${formatAmount(b.commission, "ZAR")}, ` +
          `tax R ${formatAmount(b.tax, "ZAR")}.`,
      };
    } catch {
      return { ok: true, message: `Cashed in R ${formatAmount(amount, "ZAR")}.` };
    }
  }
  if (res.status === 401 && res.body.includes("step_up_required")) {
    return { ok: false, message: res.body, needsPin: true };
  }
  if (res.status === 401 && res.body.includes("invalid_step_up_pin")) {
    return { ok: false, message: "Incorrect PIN. Try again.", needsPin: true };
  }
  return { ok: false, message: `${res.status}: ${res.body}` };
}

/**
 * Subscriber sends money to the agent (cash-out) via the user PIN/bearer flow.
 * Validates the amount, calls the backend, and surfaces any fee/commission/tax
 * breakdown on success. Handles the step-up 401 (needsPin re-prompt) exactly
 * like cashInAction, and renders a fail-closed 422 (service_not_configured)
 * legibly via describeError.
 */
export async function cashOutAction(
  subscriber: UserKey,
  amount: string,
  pin?: string,
): Promise<ActionResult> {
  const parsed = Number(amount);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false, message: "Amount must be a positive number." };
  }
  const res = await cashOut(subscriber, config.users.agent.phone, amount, pin);
  revalidatePath("/");
  if (res.ok) {
    // Surface the fee / commission / tax breakdown from the response (mirrors
    // cashin). Fields are optional — cash-out may not carry commission/tax.
    try {
      const b = JSON.parse(res.body) as {
        amount?: string;
        fee?: string;
        commission?: string;
        tax?: string;
      };
      const parts: string[] = [];
      if (b.fee) parts.push(`fee R ${formatAmount(b.fee, "ZAR")}`);
      if (b.commission)
        parts.push(`commission R ${formatAmount(b.commission, "ZAR")}`);
      if (b.tax) parts.push(`tax R ${formatAmount(b.tax, "ZAR")}`);
      const amt = b.amount ?? amount;
      const base = `Cashed out R ${formatAmount(amt, "ZAR")} to ${config.users.agent.label}`;
      return {
        ok: true,
        message: parts.length > 0 ? `${base} — ${parts.join(", ")}.` : `${base}.`,
      };
    } catch {
      return { ok: true, message: `Cashed out R ${formatAmount(amount, "ZAR")}.` };
    }
  }
  if (res.status === 401 && res.body.includes("step_up_required")) {
    return { ok: false, message: res.body, needsPin: true };
  }
  if (res.status === 401 && res.body.includes("invalid_step_up_pin")) {
    return { ok: false, message: "Incorrect PIN. Try again.", needsPin: true };
  }
  return { ok: false, message: describeError(res.status, res.body) };
}

/**
 * Change the acting subscriber's own PIN (charged self-service) via the user
 * PIN/bearer flow. Validates that both PINs are present and exactly 4 digits,
 * calls the backend, and summarises any fee/tax charged on success. Surfaces
 * wrong current PIN (401), lockout (423), insufficient funds for the fee (409),
 * and validation / fail-closed 422 (new_pin == current, invalid_pin_format,
 * service_not_configured) inline via describeError.
 */
export async function changePinAction(
  user: UserKey,
  currentPin: string,
  newPin: string,
  currency = "ZAR",
): Promise<ActionResult> {
  const isFourDigits = (pin: string) => /^\d{4}$/.test(pin);
  if (!isFourDigits(currentPin) || !isFourDigits(newPin)) {
    return { ok: false, message: "Both PINs must be exactly 4 digits." };
  }
  const res = await changePin(user, currentPin, newPin, currency);
  revalidatePath("/");
  if (res.ok) {
    // Surface the fee / tax breakdown from the response (both may be an
    // explicit zero for a zero-fee config).
    try {
      const b = JSON.parse(res.body) as {
        fee?: string;
        tax?: string;
        currency?: string;
      };
      const cur = b.currency ?? currency;
      const parts: string[] = [];
      if (b.fee) parts.push(`fee ${cur} ${formatAmount(b.fee, cur)}`);
      if (b.tax) parts.push(`tax ${cur} ${formatAmount(b.tax, cur)}`);
      return {
        ok: true,
        message:
          parts.length > 0 ? `PIN changed — ${parts.join(", ")}.` : "PIN changed.",
      };
    } catch {
      return { ok: true, message: "PIN changed." };
    }
  }
  return { ok: false, message: describeError(res.status, res.body) };
}

export async function sendP2PAction(
  sender: UserKey,
  recipient: UserKey,
  amount: string,
  pin?: string,
): Promise<ActionResult> {
  const parsed = Number(amount);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false, message: "Amount must be a positive number." };
  }
  const res = await sendP2P(sender, recipient, amount, pin);
  revalidatePath("/");
  if (res.ok) {
    return {
      ok: true,
      message: `Sent R ${formatAmount(amount, "ZAR")} from ${sender} → ${recipient}.`,
    };
  }
  // Surface the step-up flag so the UI can pop a PIN prompt without
  // parsing the error body itself.
  if (res.status === 401 && res.body.includes("step_up_required")) {
    return { ok: false, message: res.body, needsPin: true };
  }
  if (res.status === 401 && res.body.includes("invalid_step_up_pin")) {
    return { ok: false, message: "Incorrect PIN. Try again.", needsPin: true };
  }
  return { ok: false, message: `${res.status}: ${res.body}` };
}

export async function fireEventAction(
  user: UserKey,
  transactionType: string,
  amount: string,
  mode: "http" | "kafka",
): Promise<ActionResult> {
  const parsed = Number(amount);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false, message: "Amount must be a positive number." };
  }
  const fn = mode === "http" ? fireEventHttp : fireEventKafka;
  const res = await fn({ user, transactionType, amount });
  revalidatePath("/");
  if (res.ok) {
    return {
      ok: true,
      message: `${mode.toUpperCase()} ${transactionType} for ${user} — ${res.body}`,
    };
  }
  return { ok: false, message: `${res.status}: ${res.body}` };
}

export type AirtimeActionResult =
  | {
      ok: true;
      message: string;
      rechargeId: string;
      status: string;
      pending: boolean;
    }
  | { ok: false; message: string };

export async function buyAirtimeAction(
  buyer: UserKey,
  msisdn: string,
  amount: string,
): Promise<AirtimeActionResult> {
  const parsed = Number(amount);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false, message: "Amount must be a positive number." };
  }
  const res = await buyAirtime(buyer, msisdn, amount);
  revalidatePath("/");
  if (!res.ok) {
    return { ok: false, message: `${res.status}: ${res.body}` };
  }
  let body: { id: string; status: string };
  try {
    body = JSON.parse(res.body);
  } catch {
    return { ok: false, message: `Unexpected response: ${res.body}` };
  }
  const pending = body.status === "PENDING";
  const message =
    body.status === "COMPLETED"
      ? `Airtime delivered to ${msisdn} — COMPLETED.`
      : body.status === "REVERSED"
        ? `Provider declined ${msisdn} — REVERSED (fully refunded).`
        : `Accepted for ${msisdn} — PENDING (awaiting provider callback).`;
  return { ok: true, message, rechargeId: body.id, status: body.status, pending };
}

/**
 * Turn a backend error response body into a human string `error_code: message`.
 * The backend wraps errors as `{ detail: { error_code, message } }` (see
 * backend/app/shared/exceptions). Falls back to the raw text if the shape
 * differs. Used so the fail-closed pricing/limits-missing 422 is legible.
 */
function describeError(status: number, body: string): string {
  try {
    const parsed = JSON.parse(body) as {
      detail?: { error_code?: string; message?: string } | string;
    };
    const d = parsed.detail;
    if (d && typeof d === "object" && d.error_code) {
      return `${status} ${d.error_code}: ${d.message ?? ""}`.trim();
    }
    if (typeof d === "string") return `${status}: ${d}`;
  } catch {
    // Not JSON — fall through to raw body.
  }
  return `${status}: ${body}`;
}

/**
 * Fund a target user's wallet via the partner external-API (API-key + HMAC).
 * Surfaces any fee/commission/tax breakdown on success and the error_code on a
 * fail-closed 422 (service_not_configured / pricing_config_missing).
 */
export async function externalFundAction(
  targetPhone: string,
  amount: string,
  currency: string,
  reason?: string,
): Promise<ExternalActionResult> {
  const parsed = Number(amount);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false, message: "Amount must be a positive number.", status: 0, raw: "" };
  }
  const res = await externalFund(targetPhone, amount, currency, reason);
  revalidatePath("/");
  const message = res.ok
    ? summariseMoney("Funded", currency, res.body)
    : describeError(res.status, res.body);
  return { ok: res.ok, message, status: res.status, raw: res.body };
}

/**
 * Withdraw from a target user's wallet via the partner external-API. Requires
 * EXACTLY ONE of an explicit amount or the withdraw-all flag; validates that
 * mutual exclusion before calling the backend.
 */
export async function externalWithdrawAction(
  targetPhone: string,
  currency: string,
  opts: { amount?: string; withdrawAll?: boolean; reason?: string },
): Promise<ExternalActionResult> {
  if (opts.withdrawAll && opts.amount) {
    return {
      ok: false,
      message: "Choose either an amount or Withdraw all — not both.",
      status: 0,
      raw: "",
    };
  }
  if (!opts.withdrawAll) {
    const parsed = Number(opts.amount);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return {
        ok: false,
        message: "Enter a positive amount, or toggle Withdraw all.",
        status: 0,
        raw: "",
      };
    }
  }
  const res = await externalWithdraw(targetPhone, currency, opts);
  revalidatePath("/");
  const message = res.ok
    ? summariseMoney("Withdrew", currency, res.body)
    : describeError(res.status, res.body);
  return { ok: res.ok, message, status: res.status, raw: res.body };
}

/**
 * Merchant cash-in via the partner external-API: debit the merchant's own wallet
 * (resolved from the API key) and credit the CONSUMER target by phone. Surfaces
 * any fee/commission/tax breakdown on success and the error_code on a fail-closed
 * 422 (service_not_configured), a 409 (insufficient_funds), or a 403
 * (not_a_merchant_key) via describeError.
 */
export async function merchantCashinAction(
  targetPhone: string,
  amount: string,
  currency: string,
  reason?: string,
): Promise<ExternalActionResult> {
  const parsed = Number(amount);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false, message: "Amount must be a positive number.", status: 0, raw: "" };
  }
  const res = await merchantCashin(targetPhone, amount, currency, reason);
  revalidatePath("/");
  const message = res.ok
    ? summariseMoney("Cashed in", currency, res.body)
    : describeError(res.status, res.body);
  return { ok: res.ok, message, status: res.status, raw: res.body };
}

/**
 * Create a user from partner-supplied identifiers via the external-API. Reports
 * created (HTTP 201) vs already-existing (HTTP 200 — the identifier is the
 * idempotency key) distinctly, and surfaces the error_code on a 422.
 */
export async function externalCreateUserAction(
  identifiers: ExternalIdentifier[],
): Promise<ExternalActionResult> {
  const cleaned = identifiers.filter((i) => i.identifier_value.trim() !== "");
  if (cleaned.length === 0) {
    return { ok: false, message: "Add at least one identifier.", status: 0, raw: "" };
  }
  const res = await externalCreateUser(cleaned);
  revalidatePath("/");
  if (!res.ok) {
    return {
      ok: false,
      message: describeError(res.status, res.body),
      status: res.status,
      raw: res.body,
    };
  }
  let userId = "?";
  try {
    userId = (JSON.parse(res.body) as { id?: string }).id ?? "?";
  } catch {
    // Non-JSON success body — keep the placeholder id.
  }
  const message =
    res.status === 201
      ? `Created user ${userId}.`
      : `User already exists: ${userId} (matched an existing identifier).`;
  return { ok: true, message, status: res.status, raw: res.body };
}

/**
 * Build a success message from an external fund/withdraw response, appending any
 * fee/commission/tax fields the backend returned. `verb` is the past-tense
 * action word (e.g. "Funded"). Falls back to a bare confirmation if the body is
 * not the expected JSON shape.
 */
function summariseMoney(verb: string, currency: string, body: string): string {
  try {
    const b = JSON.parse(body) as {
      amount?: string;
      fee?: string;
      commission?: string;
      tax?: string;
    };
    const parts: string[] = [];
    if (b.fee) parts.push(`fee ${formatAmount(b.fee, currency)}`);
    if (b.commission)
      parts.push(`commission ${formatAmount(b.commission, currency)}`);
    if (b.tax) parts.push(`tax ${formatAmount(b.tax, currency)}`);
    const amount = b.amount ? formatAmount(b.amount, currency) : "";
    const base = `${verb} ${currency} ${amount}`.trim();
    return parts.length > 0 ? `${base} — ${parts.join(", ")}.` : `${base}.`;
  } catch {
    return `${verb} — ${body}`;
  }
}

export async function simulateAirtimeCallbackAction(
  rechargeId: string,
  outcome: "completed" | "failed",
): Promise<ActionResult> {
  const res = await simulateAirtimeCallback(rechargeId, outcome);
  revalidatePath("/");
  if (!res.ok) {
    return { ok: false, message: `${res.status}: ${res.body}` };
  }
  return {
    ok: true,
    message:
      outcome === "completed"
        ? "Provider callback → COMPLETED."
        : "Provider callback → REVERSED (refunded).",
  };
}
