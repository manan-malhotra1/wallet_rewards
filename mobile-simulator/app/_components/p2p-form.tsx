/**
 * <P2PForm> — small inline form that triggers the sendP2PAction.
 *
 * Two-step flow when the backend's step-up policy applies:
 *   1. User clicks Send → server returns 401 step_up_required.
 *   2. UI reveals a PIN input + retries Send with the PIN.
 *
 * Client component so the PIN prompt can stay inline without a full
 * page navigation. The PIN itself never touches localStorage — held
 * only in this component's transient state.
 */
"use client";

import { ArrowRightCircle, KeyRound } from "lucide-react";
import * as React from "react";
import { useFormStatus } from "react-dom";

import { sendP2PAction } from "@/app/_actions";
import type { UserKey } from "@/lib/config";

function SubmitButton({ label }: { label: string }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="flex items-center justify-center gap-1.5 rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:opacity-50"
    >
      <ArrowRightCircle className="h-4 w-4" />
      {pending ? "Sending…" : label}
    </button>
  );
}

export function P2PForm({
  sender,
  recipient,
}: {
  sender: UserKey;
  recipient: UserKey;
}) {
  const [amount, setAmount] = React.useState("50");
  const [pin, setPin] = React.useState("");
  const [needsPin, setNeedsPin] = React.useState(false);
  const [status, setStatus] = React.useState<{
    ok: boolean;
    msg: string;
  } | null>(null);

  async function action() {
    const result = await sendP2PAction(sender, recipient, amount, pin || undefined);
    if (result.ok) {
      setStatus({ ok: true, msg: result.message });
      setNeedsPin(false);
      setPin("");
      return;
    }
    setStatus({ ok: false, msg: result.message });
    if (result.needsPin) {
      setNeedsPin(true);
    } else {
      setNeedsPin(false);
      setPin("");
    }
  }

  const recipientLabel = recipient[0].toUpperCase() + recipient.slice(1);

  return (
    <form action={action} className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-xs text-[var(--color-fg-muted)]">R</span>
        <input
          type="number"
          step="0.01"
          min="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className="w-24 rounded-md border border-[var(--color-border)] bg-white px-2 py-1.5 text-sm tabular-nums"
        />
        <SubmitButton label={`Send to ${recipientLabel}`} />
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
            Amount above the step-up threshold — re-enter PIN and Send again.
          </span>
        </div>
      )}
      {status ? (
        <div
          className={
            "text-[11px] " +
            (status.ok ? "text-[var(--color-success)]" : "text-[var(--color-danger)]")
          }
        >
          {status.msg}
        </div>
      ) : null}
    </form>
  );
}
