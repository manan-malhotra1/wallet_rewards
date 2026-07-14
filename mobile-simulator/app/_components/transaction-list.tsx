/**
 * <TransactionList> — the "Recent activity" feed inside a wallet pane.
 *
 * Shows the latest 4 transactions by default; a "Show more" toggle
 * reveals the rest, capped at 20 total. Client component so the toggle
 * and relative timestamps run against the viewer's clock.
 */
"use client";

import { ChevronDown, ChevronUp } from "lucide-react";
import * as React from "react";

import type { WalletTransaction } from "@/lib/backend";
import { formatAmount, relativeTime, transactionTypeLabel } from "@/lib/format";

const VISIBLE = 4;
const MAX = 20;

export function TransactionList({
  transactions,
}: {
  transactions: WalletTransaction[];
}) {
  const [expanded, setExpanded] = React.useState(false);

  if (transactions.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-[var(--color-border)] px-4 py-3 text-xs text-[var(--color-fg-muted)]">
        No transactions yet.
      </div>
    );
  }

  // Never render more than MAX; collapse to the latest VISIBLE.
  const capped = transactions.slice(0, MAX);
  const shown = expanded ? capped : capped.slice(0, VISIBLE);
  const hidden = capped.length - shown.length;

  return (
    <>
      <ul className="flex flex-col gap-1.5">
        {shown.map((txn) => (
          <li
            key={txn.id}
            className="flex items-center justify-between rounded-lg border border-[var(--color-border)] px-3 py-2 text-sm"
          >
            <div>
              <div className="font-medium text-[var(--color-fg)]">
                {transactionTypeLabel(txn.transaction_type)}
              </div>
              <div className="text-[11px] text-[var(--color-fg-muted)]">
                {relativeTime(txn.created_at)} · {txn.status}
              </div>
            </div>
            <div className="font-mono tabular-nums text-[var(--color-fg)]">
              {formatAmount(txn.amount, txn.currency)} {txn.currency}
            </div>
          </li>
        ))}
      </ul>

      {capped.length > VISIBLE ? (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="mt-2 flex items-center justify-center gap-1 rounded-md border border-[var(--color-border)] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)] transition hover:text-[var(--color-fg)]"
        >
          {expanded ? (
            <>
              <ChevronUp className="h-3.5 w-3.5" /> Show less
            </>
          ) : (
            <>
              <ChevronDown className="h-3.5 w-3.5" /> Show {hidden} more
            </>
          )}
        </button>
      ) : null}
    </>
  );
}
