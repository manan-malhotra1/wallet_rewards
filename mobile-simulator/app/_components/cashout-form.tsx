/**
 * <CashOutForm> — a subscriber sends money to the agent (cash-out): the
 * subscriber is debited (amount + fee) and the agent credited. The success
 * message shows any fee / commission / tax breakdown returned by the backend.
 *
 * Mirrors <CashInForm>'s inline step-up flow: if the amount is over the step-up
 * threshold the backend returns 401, and the UI reveals a PIN input to retry.
 * Client component; the PIN lives only in transient state.
 */
"use client";

import { KeyRound, Landmark } from "lucide-react";
import * as React from "react";
import { useFormStatus } from "react-dom";

import { cashOutAction } from "@/app/_actions";
import type { UserKey } from "@/lib/config";

// The agent is the fixed recipient (Grace). Label inlined so this client
// component doesn't import the server-only `config`.
const AGENT_LABEL = "Grace (Agent)";

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="flex items-center justify-center gap-1.5 rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:opacity-50"
    >
      <Landmark className="h-4 w-4" />
      {pending ? "Cashing out…" : "Cash out"}
    </button>
  );
}

export function CashOutForm({ subscriber }: { subscriber: UserKey }) {
  const [amount, setAmount] = React.useState("100");
  const [pin, setPin] = React.useState("");
  const [needsPin, setNeedsPin] = React.useState(false);
  const [status, setStatus] = React.useState<{ ok: boolean; msg: string } | null>(
    null,
  );

  async function action() {
    const result = await cashOutAction(subscriber, amount, pin || undefined);
    if (result.ok) {
      setStatus({ ok: true, msg: result.message });
      setNeedsPin(false);
      setPin("");
      return;
    }
    setStatus({ ok: false, msg: result.message });
    setNeedsPin(Boolean(result.needsPin));
    if (!result.needsPin) setPin("");
  }

  return (
    <div className="mt-3 border-t border-[var(--color-border)] pt-3">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)]">
        Cash out (→ {AGENT_LABEL})
      </div>
      <form action={action} className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-[var(--color-fg-muted)]">R</span>
          <input
            type="number"
            step="0.01"
            min="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-24 rounded-md border border-[var(--color-border)] bg-white px-2 py-1.5 text-sm tabular-nums"
          />
          <SubmitButton />
        </div>
        {needsPin && (
          <div className="flex items-center gap-2 rounded-md border border-[var(--color-teal)] bg-[var(--color-teal)]/10 px-2 py-1.5">
            <KeyRound className="h-3.5 w-3.5 text-[var(--color-brand)]" />
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-brand)]">
              PIN
            </span>
            <input
              type="password"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={pin}
              onChange={(e) => setPin(e.target.value)}
              placeholder="1234"
              maxLength={6}
              className="w-20 rounded-md border border-[var(--color-border)] bg-white px-2 py-1 text-sm tabular-nums tracking-widest"
            />
            <span className="text-[10px] text-[var(--color-fg-muted)]">
              Amount above the step-up threshold — re-enter PIN and Cash out again.
            </span>
          </div>
        )}
      </form>
      {status ? (
        <div
          className={
            "mt-1 text-[11px] " +
            (status.ok
              ? "text-[var(--color-success)]"
              : "text-[var(--color-danger)]")
          }
        >
          {status.msg}
        </div>
      ) : null}
    </div>
  );
}
