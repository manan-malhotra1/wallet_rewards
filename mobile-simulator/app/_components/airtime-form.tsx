/**
 * <AirtimeForm> — buy airtime as `buyer`, driving the backend's simulator
 * provider by picking an outcome.
 *
 * The bundled SimulatorProvider decides success/fail/pending from the target
 * msisdn suffix (…0001 fail, …0002 pending, else success), so this form maps a
 * friendly outcome picker onto a "magic" msisdn. A PENDING recharge does not
 * resolve on its own — the provider never calls back — so when one lands we
 * reveal buttons that POST a signed provider callback to finalise it.
 *
 * Client component so the pending → callback step stays inline; PINs/secrets
 * never touch the browser (the server actions hold them).
 */
"use client";

import { PhoneCall, Smartphone } from "lucide-react";
import * as React from "react";
import { useFormStatus } from "react-dom";

import { buyAirtimeAction, simulateAirtimeCallbackAction } from "@/app/_actions";
import type { UserKey } from "@/lib/config";

// Maps a friendly outcome to a "magic" target msisdn the simulator recognises.
const OUTCOMES = {
  success: { label: "Success", msisdn: "+27831112222" },
  failed: { label: "Failure (reversed)", msisdn: "+27820000001" },
  pending: { label: "Pending (needs callback)", msisdn: "+27820000002" },
} as const;
type OutcomeKey = keyof typeof OUTCOMES;

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="flex items-center justify-center gap-1.5 rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:opacity-50"
    >
      <Smartphone className="h-4 w-4" />
      {pending ? "Buying…" : "Buy airtime"}
    </button>
  );
}

export function AirtimeForm({ buyer }: { buyer: UserKey }) {
  const [amount, setAmount] = React.useState("50");
  const [outcome, setOutcome] = React.useState<OutcomeKey>("success");
  const [status, setStatus] = React.useState<{ ok: boolean; msg: string } | null>(
    null,
  );
  const [pendingId, setPendingId] = React.useState<string | null>(null);
  const [cbBusy, setCbBusy] = React.useState(false);

  async function action() {
    setPendingId(null);
    const result = await buyAirtimeAction(buyer, OUTCOMES[outcome].msisdn, amount);
    if (result.ok) {
      setStatus({ ok: result.status !== "REVERSED", msg: result.message });
      setPendingId(result.pending ? result.rechargeId : null);
    } else {
      setStatus({ ok: false, msg: result.message });
    }
  }

  async function fireCallback(cb: "completed" | "failed") {
    if (!pendingId) return;
    setCbBusy(true);
    const result = await simulateAirtimeCallbackAction(pendingId, cb);
    setCbBusy(false);
    setStatus({ ok: cb === "completed" && result.ok, msg: result.message });
    if (result.ok) setPendingId(null);
  }

  return (
    <div className="mt-3 border-t border-[var(--color-border)] pt-3">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)]">
        Buy airtime
      </div>
      <form action={action} className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as OutcomeKey)}
            className="rounded-md border border-[var(--color-border)] bg-white px-2 py-1.5 text-sm"
          >
            {Object.entries(OUTCOMES).map(([key, o]) => (
              <option key={key} value={key}>
                {o.label}
              </option>
            ))}
          </select>
          <span className="text-xs text-[var(--color-fg-muted)]">R</span>
          <input
            type="number"
            step="0.01"
            min="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-20 rounded-md border border-[var(--color-border)] bg-white px-2 py-1.5 text-sm tabular-nums"
          />
          <SubmitButton />
        </div>
        <div className="font-mono text-[10px] text-[var(--color-fg-muted)]">
          → {OUTCOMES[outcome].msisdn} · min R5 / max R1000 · R1 fee
        </div>
      </form>

      {pendingId ? (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-[var(--color-teal)] bg-[var(--color-teal)]/10 px-2 py-1.5">
          <PhoneCall className="h-3.5 w-3.5 text-[var(--color-brand)]" />
          <span className="text-[11px] text-[var(--color-fg-muted)]">
            Provider hasn&apos;t called back yet:
          </span>
          <button
            type="button"
            disabled={cbBusy}
            onClick={() => fireCallback("completed")}
            className="rounded bg-[var(--color-success)] px-2 py-1 text-[11px] font-medium text-white transition hover:opacity-90 disabled:opacity-50"
          >
            Callback → complete
          </button>
          <button
            type="button"
            disabled={cbBusy}
            onClick={() => fireCallback("failed")}
            className="rounded border border-[var(--color-danger)] px-2 py-1 text-[11px] font-medium text-[var(--color-danger)] transition hover:bg-red-50 disabled:opacity-50"
          >
            → fail
          </button>
        </div>
      ) : null}

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
