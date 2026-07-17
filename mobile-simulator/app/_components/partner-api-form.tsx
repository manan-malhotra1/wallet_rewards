/**
 * <PartnerApiForm> — exercises the partner external-API endpoints, which use
 * API-key + HMAC auth (X-Sasai-Api-Key + X-Sasai-Signature) rather than the
 * user PIN/bearer flow. Three sub-forms in one card:
 *
 *   • Fund     — POST /external/fund            (credit a user's financial wallet)
 *   • Withdraw — POST /external/withdraw        (debit; exactly one of amount / all)
 *   • Cash-in  — POST /external/merchant-cashin (debit merchant, credit consumer)
 *   • Create   — POST /external/users           (create/idempotent-match a user)
 *
 * Client component: it holds transient form state and renders the raw status +
 * response after each fire. Secrets never reach the browser — the server
 * actions sign and send. A fail-closed 422 (service_not_configured /
 * pricing_config_missing) is an expected, clearly-surfaced outcome for
 * fund/withdraw until a pricing+limits config exists.
 */
"use client";

import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Plus,
  Store,
  UserPlus,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import {
  externalCreateUserAction,
  externalFundAction,
  externalWithdrawAction,
  merchantCashinAction,
  type ExternalActionResult,
} from "@/app/_actions";
import type { ExternalIdentifier } from "@/lib/backend";
import { usePersistedState } from "@/lib/use-persisted-state";

/** A configured simulator user offered as a fund/withdraw target. */
export interface TargetUser {
  label: string;
  phone: string;
}

const IDENTIFIER_TYPES: ExternalIdentifier["identifier_type"][] = [
  "phone",
  "email",
  "account_number",
  "card_number",
];

const inputClass =
  "rounded-md border border-[var(--color-border)] bg-white px-2 py-1.5 text-sm";

/** Coloured raw-response box shown after any of the three fires. */
function ResultBox({ result }: { result: ExternalActionResult }) {
  return (
    <div
      className={
        "mt-2 space-y-1 rounded-md border px-3 py-2 text-[11px] " +
        (result.ok
          ? "border-[var(--color-success)] bg-green-50 text-[var(--color-success)]"
          : "border-[var(--color-danger)] bg-red-50 text-[var(--color-danger)]")
      }
    >
      <div className="font-medium">{result.message}</div>
      {result.status > 0 ? (
        <div className="font-mono text-[10px] break-all whitespace-pre-wrap opacity-80">
          HTTP {result.status} · {result.raw || "(empty body)"}
        </div>
      ) : null}
    </div>
  );
}

function FundForm({ users }: { users: TargetUser[] }) {
  const [phone, setPhone] = usePersistedState(
    "sim.ext.fund.phone",
    users[0]?.phone ?? "",
  );
  const [amount, setAmount] = usePersistedState("sim.ext.fund.amount", "100");
  const [currency, setCurrency] = usePersistedState("sim.ext.fund.currency", "ZAR");
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<ExternalActionResult | null>(null);
  const router = useRouter();

  async function action() {
    setBusy(true);
    const r = await externalFundAction(phone, amount, currency, reason || undefined);
    setBusy(false);
    setResult(r);
    router.refresh();
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)]">
        <ArrowDownToLine className="h-3.5 w-3.5" /> Fund (credit wallet)
      </div>
      <form action={action} className="flex flex-wrap items-center gap-2">
        <select
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          className={inputClass}
        >
          {users.map((u) => (
            <option key={u.phone} value={u.phone}>
              {u.label} ({u.phone})
            </option>
          ))}
        </select>
        <input
          type="number"
          step="0.01"
          min="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className={`${inputClass} w-24 tabular-nums`}
        />
        <input
          value={currency}
          onChange={(e) => setCurrency(e.target.value.toUpperCase())}
          className={`${inputClass} w-20`}
          aria-label="Currency"
        />
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="reason (optional)"
          className={`${inputClass} min-w-40 flex-1`}
        />
        <button
          type="submit"
          disabled={busy}
          className="flex items-center gap-1.5 rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:opacity-50"
        >
          <ArrowDownToLine className="h-4 w-4" />
          {busy ? "Funding…" : "Fund"}
        </button>
      </form>
      {result ? <ResultBox result={result} /> : null}
    </div>
  );
}

function WithdrawForm({ users }: { users: TargetUser[] }) {
  const [phone, setPhone] = usePersistedState(
    "sim.ext.wd.phone",
    users[0]?.phone ?? "",
  );
  const [amount, setAmount] = usePersistedState("sim.ext.wd.amount", "50");
  const [currency, setCurrency] = usePersistedState("sim.ext.wd.currency", "ZAR");
  const [withdrawAll, setWithdrawAll] = usePersistedState(
    "sim.ext.wd.all",
    false,
  );
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<ExternalActionResult | null>(null);
  const router = useRouter();

  async function action() {
    setBusy(true);
    const r = await externalWithdrawAction(phone, currency, {
      // Exactly one of amount / withdrawAll — enforced by the toggle disabling
      // the amount input, and re-checked in the action.
      amount: withdrawAll ? undefined : amount,
      withdrawAll,
      reason: reason || undefined,
    });
    setBusy(false);
    setResult(r);
    router.refresh();
  }

  return (
    <div className="border-t border-[var(--color-border)] pt-4">
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)]">
        <ArrowUpFromLine className="h-3.5 w-3.5" /> Withdraw (debit wallet)
      </div>
      <form action={action} className="flex flex-wrap items-center gap-2">
        <select
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          className={inputClass}
        >
          {users.map((u) => (
            <option key={u.phone} value={u.phone}>
              {u.label} ({u.phone})
            </option>
          ))}
        </select>
        <input
          type="number"
          step="0.01"
          min="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          disabled={withdrawAll}
          className={`${inputClass} w-24 tabular-nums disabled:opacity-40`}
        />
        <label className="flex items-center gap-1.5 text-xs text-[var(--color-fg)]">
          <input
            type="checkbox"
            checked={withdrawAll}
            onChange={(e) => setWithdrawAll(e.target.checked)}
          />
          Withdraw all
        </label>
        <input
          value={currency}
          onChange={(e) => setCurrency(e.target.value.toUpperCase())}
          className={`${inputClass} w-20`}
          aria-label="Currency"
        />
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="reason (optional)"
          className={`${inputClass} min-w-40 flex-1`}
        />
        <button
          type="submit"
          disabled={busy}
          className="flex items-center gap-1.5 rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:opacity-50"
        >
          <ArrowUpFromLine className="h-4 w-4" />
          {busy ? "Withdrawing…" : "Withdraw"}
        </button>
      </form>
      {result ? <ResultBox result={result} /> : null}
    </div>
  );
}

function MerchantCashinForm({ users }: { users: TargetUser[] }) {
  const [phone, setPhone] = usePersistedState(
    "sim.ext.mcashin.phone",
    users[0]?.phone ?? "",
  );
  const [amount, setAmount] = usePersistedState("sim.ext.mcashin.amount", "100");
  const [currency, setCurrency] = usePersistedState(
    "sim.ext.mcashin.currency",
    "ZAR",
  );
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<ExternalActionResult | null>(null);
  const router = useRouter();

  async function action() {
    setBusy(true);
    const r = await merchantCashinAction(phone, amount, currency, reason || undefined);
    setBusy(false);
    setResult(r);
    router.refresh();
  }

  return (
    <div className="border-t border-[var(--color-border)] pt-4">
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)]">
        <Store className="h-3.5 w-3.5" /> Merchant cash-in (funds a consumer from
        the merchant&apos;s wallet)
      </div>
      <form action={action} className="flex flex-wrap items-center gap-2">
        <select
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          className={inputClass}
        >
          {users.map((u) => (
            <option key={u.phone} value={u.phone}>
              {u.label} ({u.phone})
            </option>
          ))}
        </select>
        <input
          type="number"
          step="0.01"
          min="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className={`${inputClass} w-24 tabular-nums`}
        />
        <input
          value={currency}
          onChange={(e) => setCurrency(e.target.value.toUpperCase())}
          className={`${inputClass} w-20`}
          aria-label="Currency"
        />
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="reason (optional)"
          className={`${inputClass} min-w-40 flex-1`}
        />
        <button
          type="submit"
          disabled={busy}
          className="flex items-center gap-1.5 rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:opacity-50"
        >
          <Store className="h-4 w-4" />
          {busy ? "Cashing in…" : "Cash in"}
        </button>
      </form>
      {result ? <ResultBox result={result} /> : null}
    </div>
  );
}

function CreateUserForm() {
  const [rows, setRows] = React.useState<ExternalIdentifier[]>([
    { identifier_type: "phone", identifier_value: "" },
  ]);
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<ExternalActionResult | null>(null);
  const router = useRouter();

  function update(index: number, patch: Partial<ExternalIdentifier>) {
    setRows((prev) =>
      prev.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    );
  }

  async function action() {
    setBusy(true);
    const r = await externalCreateUserAction(rows);
    setBusy(false);
    setResult(r);
    router.refresh();
  }

  return (
    <div className="border-t border-[var(--color-border)] pt-4">
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)]">
        <UserPlus className="h-3.5 w-3.5" /> Create user (≥1 identifier, incl. an
        email or phone)
      </div>
      <form action={action} className="flex flex-col gap-2">
        {rows.map((row, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <select
              value={row.identifier_type}
              onChange={(e) =>
                update(i, {
                  identifier_type: e.target
                    .value as ExternalIdentifier["identifier_type"],
                })
              }
              className={inputClass}
            >
              {IDENTIFIER_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <input
              value={row.identifier_value}
              onChange={(e) => update(i, { identifier_value: e.target.value })}
              placeholder="value"
              className={`${inputClass} min-w-48 flex-1`}
            />
            {rows.length > 1 ? (
              <button
                type="button"
                onClick={() => setRows((prev) => prev.filter((_, j) => j !== i))}
                className="rounded-md border border-[var(--color-border)] p-1.5 text-[var(--color-fg-muted)] transition hover:text-[var(--color-danger)]"
                aria-label="Remove identifier"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
        ))}
        <div className="flex items-center gap-2">
          {rows.length < 2 ? (
            <button
              type="button"
              onClick={() =>
                setRows((prev) => [
                  ...prev,
                  { identifier_type: "email", identifier_value: "" },
                ])
              }
              className="flex items-center gap-1 rounded-md border border-[var(--color-border)] px-2 py-1.5 text-xs text-[var(--color-fg-muted)] transition hover:text-[var(--color-fg)]"
            >
              <Plus className="h-3.5 w-3.5" /> Add identifier
            </button>
          ) : null}
          <button
            type="submit"
            disabled={busy}
            className="flex items-center gap-1.5 rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:opacity-50"
          >
            <UserPlus className="h-4 w-4" />
            {busy ? "Creating…" : "Create user"}
          </button>
        </div>
      </form>
      {result ? <ResultBox result={result} /> : null}
    </div>
  );
}

export function PartnerApiForm({ users }: { users: TargetUser[] }) {
  return (
    <section className="rounded-2xl border border-[var(--color-border)] bg-white p-5 shadow-sm">
      <header className="mb-4 border-b border-[var(--color-border)] pb-3">
        <div className="text-base font-semibold text-[var(--color-fg)]">
          Partner APIs (external fund / withdraw)
        </div>
        <div className="mt-0.5 text-xs text-[var(--color-fg-muted)]">
          API-key + HMAC auth (no user PIN). Tenant is derived from the key. Until
          a fund/withdraw pricing+limits config exists, a{" "}
          <span className="font-mono">422 service_not_configured</span> is
          expected.
        </div>
      </header>
      <div className="flex flex-col gap-4">
        <FundForm users={users} />
        <WithdrawForm users={users} />
        <MerchantCashinForm users={users} />
        <CreateUserForm />
      </div>
    </section>
  );
}
