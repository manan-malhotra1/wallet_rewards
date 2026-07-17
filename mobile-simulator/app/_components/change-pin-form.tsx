/**
 * <ChangePinForm> — a subscriber changes their own PIN (charged self-service):
 * a fee (+tax) may be debited on success. Mirrors <CashOutForm>: a per-user
 * client form whose PINs live only in transient state and reach the backend via
 * the changePinAction server action (never fetched from the browser).
 */
"use client";

import { KeyRound } from "lucide-react";
import * as React from "react";
import { useFormStatus } from "react-dom";

import { changePinAction } from "@/app/_actions";
import type { UserKey } from "@/lib/config";

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="flex items-center justify-center gap-1.5 rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:opacity-90 disabled:opacity-50"
    >
      <KeyRound className="h-4 w-4" />
      {pending ? "Changing…" : "Change PIN"}
    </button>
  );
}

export function ChangePinForm({ user }: { user: UserKey }) {
  const [currentPin, setCurrentPin] = React.useState("");
  const [newPin, setNewPin] = React.useState("");
  const [status, setStatus] = React.useState<{ ok: boolean; msg: string } | null>(
    null,
  );

  async function action() {
    const result = await changePinAction(user, currentPin, newPin);
    setStatus({ ok: result.ok, msg: result.message });
    if (result.ok) {
      // Clear the inputs so the next change starts fresh; keep PINs only in
      // transient state and never in the DOM after a successful change.
      setCurrentPin("");
      setNewPin("");
    }
  }

  const pinInputClass =
    "w-24 rounded-md border border-[var(--color-border)] bg-white px-2 py-1.5 text-sm tabular-nums tracking-widest";

  return (
    <div className="mt-3 border-t border-[var(--color-border)] pt-3">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)]">
        Change PIN
      </div>
      <form action={action} className="flex flex-wrap items-center gap-2">
        <input
          type="password"
          inputMode="numeric"
          autoComplete="off"
          value={currentPin}
          onChange={(e) => setCurrentPin(e.target.value)}
          placeholder="Current"
          maxLength={4}
          aria-label="Current PIN"
          className={pinInputClass}
        />
        <input
          type="password"
          inputMode="numeric"
          autoComplete="off"
          value={newPin}
          onChange={(e) => setNewPin(e.target.value)}
          placeholder="New"
          maxLength={4}
          aria-label="New PIN"
          className={pinInputClass}
        />
        <SubmitButton />
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
