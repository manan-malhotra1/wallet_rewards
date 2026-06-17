/**
 * <EventTrigger> — fire a Kafka/HTTP campaign-test event.
 *
 * The bottom panel of the simulator. Pick a recipient, an event type,
 * an amount, and whether to go through the synchronous HTTP path or
 * the real Kafka producer. The body matches the platform's standard
 * NormalisedEvent schema (Pay-PRD-0490) so any active rule will fire.
 */
"use client";

import { Zap } from "lucide-react";
import * as React from "react";
import { useFormStatus } from "react-dom";

import { fireEventAction } from "@/app/_actions";
import type { UserKey } from "@/lib/config";

const EVENT_TYPES = [
  { value: "top_up", label: "Top-up" },
  { value: "p2p", label: "P2P (synthetic)" },
  { value: "redeem", label: "Redeem" },
  { value: "merchant_pay", label: "Merchant pay" },
];

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="flex items-center justify-center gap-1.5 rounded-md bg-[var(--color-teal)] px-4 py-2 text-sm font-semibold text-[var(--color-brand)] shadow-sm transition hover:brightness-105 disabled:opacity-50"
    >
      <Zap className="h-4 w-4" />
      {pending ? "Firing…" : "Fire event"}
    </button>
  );
}

export function EventTrigger() {
  const [user, setUser] = React.useState<UserKey>("alice");
  const [eventType, setEventType] = React.useState("top_up");
  const [amount, setAmount] = React.useState("500");
  const [mode, setMode] = React.useState<"http" | "kafka">("http");
  const [status, setStatus] = React.useState<{
    ok: boolean;
    msg: string;
  } | null>(null);

  async function action() {
    const result = await fireEventAction(user, eventType, amount, mode);
    setStatus({ ok: result.ok, msg: result.message });
  }

  return (
    <section className="rounded-2xl border border-[var(--color-border)] bg-white p-5 shadow-sm">
      <header className="mb-4 flex items-center justify-between border-b border-[var(--color-border)] pb-3">
        <div>
          <div className="text-base font-semibold text-[var(--color-fg)]">
            Campaign event trigger
          </div>
          <div className="mt-0.5 text-xs text-[var(--color-fg-muted)]">
            Fire a test event so an active rule can evaluate + reward.
          </div>
        </div>
        <div className="flex items-center gap-1 rounded-full bg-[var(--color-bg)] p-1 text-xs">
          {(["http", "kafka"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={
                "rounded-full px-3 py-1 font-semibold uppercase tracking-wider transition " +
                (mode === m
                  ? "bg-[var(--color-brand)] text-white shadow"
                  : "text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]")
              }
            >
              {m}
            </button>
          ))}
        </div>
      </header>

      <form action={action} className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)]">
            User
          </span>
          <select
            value={user}
            onChange={(e) => setUser(e.target.value as UserKey)}
            className="rounded-md border border-[var(--color-border)] bg-white px-2 py-1.5 text-sm"
          >
            <option value="alice">Alice</option>
            <option value="bob">Bob</option>
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)]">
            Event type
          </span>
          <select
            value={eventType}
            onChange={(e) => setEventType(e.target.value)}
            className="rounded-md border border-[var(--color-border)] bg-white px-2 py-1.5 text-sm"
          >
            {EVENT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)]">
            Amount (ZAR)
          </span>
          <input
            type="number"
            step="0.01"
            min="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-28 rounded-md border border-[var(--color-border)] bg-white px-2 py-1.5 text-sm tabular-nums"
          />
        </label>

        <SubmitButton />
      </form>

      {status ? (
        <div
          className={
            "mt-3 max-h-32 overflow-auto rounded-md border px-3 py-2 font-mono text-[11px] " +
            (status.ok
              ? "border-[var(--color-success)] bg-green-50 text-[var(--color-success)]"
              : "border-[var(--color-danger)] bg-red-50 text-[var(--color-danger)]")
          }
        >
          {status.msg}
        </div>
      ) : null}
    </section>
  );
}
