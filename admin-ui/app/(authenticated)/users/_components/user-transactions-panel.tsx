/**
 * <UserTransactionsPanel> — the paged, filterable transaction table on the
 * user-detail page.
 *
 * Everything narrowing happens SERVER-side (`fetchUserTransactionsAction`), so
 * finding one movement never depends on how much of the ledger the page
 * happened to load:
 *   - currency chips (All / the user's own wallet currencies / PTS);
 *   - reference search — paste a full "S_2026…" id or type part of one;
 *   - 20 rows a page with "m–n of N" and Prev / Next.
 *
 * The first page is server-rendered by the parent and handed in as
 * `initialItems` / `initialTotal`, so the panel paints with data and only
 * re-fetches once the operator actually filters or pages.
 */
"use client";

import { Search, X } from "lucide-react";
import * as React from "react";

import { fetchUserTransactionsAction } from "@/app/(authenticated)/users/_actions";
import { Money, Points } from "@/components/ui/money";
import { Input } from "@/components/ui/input";
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import type { UserTransaction } from "@/lib/api-endpoints";
import { transactionTypeLabel } from "@/lib/transaction-type-label";
import { cn, formatTimestamp, shortId } from "@/lib/utils";

import { CounterpartyCell } from "./counterparty-cell";

const PAGE_SIZE = 20;

/** One currency filter chip. */
function CurrencyChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border text-muted-foreground hover:bg-muted",
      )}
    >
      {label}
    </button>
  );
}

export function UserTransactionsPanel({
  tenantId,
  userId,
  initialItems,
  initialTotal,
  currencies,
}: {
  tenantId: string;
  userId: string;
  /** Server-rendered first page — the panel paints with this. */
  initialItems: UserTransaction[];
  initialTotal: number;
  /** The user's own wallet currencies; PTS is appended when they hold points. */
  currencies: string[];
}) {
  const [items, setItems] = React.useState(initialItems);
  const [total, setTotal] = React.useState(initialTotal);
  const [offset, setOffset] = React.useState(0);
  const [currency, setCurrency] = React.useState<string | null>(null);
  // `query` is what the operator is typing; `search` is what's been submitted.
  // Keeping them apart means we hit the server on Enter / clear, not per key.
  const [query, setQuery] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  // Skip the fetch on first paint — the parent already server-rendered page 1.
  const primed = React.useRef(false);

  React.useEffect(() => {
    if (!primed.current) {
      primed.current = true;
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchUserTransactionsAction(tenantId, userId, {
      limit: PAGE_SIZE,
      offset,
      ...(currency ? { currency } : {}),
      ...(search ? { q: search } : {}),
    }).then((res) => {
      if (cancelled) return;
      setLoading(false);
      if (res.ok) {
        setItems(res.items);
        setTotal(res.total);
      } else {
        setError(`${res.errorCode}: ${res.message}`);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId, offset, currency, search]);

  /** Any filter change resets to page 1 — page 3 of the old result is meaningless. */
  function applyCurrency(next: string | null) {
    setCurrency(next);
    setOffset(0);
  }

  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    setSearch(query.trim());
    setOffset(0);
  }

  function clearSearch() {
    setQuery("");
    setSearch("");
    setOffset(0);
  }

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + items.length, total);
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <div className="space-y-3">
      {/* Controls — currency chips + reference search. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <CurrencyChip
            label="All"
            active={currency === null}
            onClick={() => applyCurrency(null)}
          />
          {currencies.map((c) => (
            <CurrencyChip
              key={c}
              label={c}
              active={currency === c}
              onClick={() => applyCurrency(c)}
            />
          ))}
        </div>
        <form onSubmit={submitSearch} className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search transaction ID…"
            aria-label="Search transaction ID"
            className="h-8 w-64 pl-8 pr-7 text-xs"
          />
          {query ? (
            <button
              type="button"
              onClick={clearSearch}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          ) : null}
        </form>
      </div>

      {error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {search || currency
            ? "No transactions match these filters."
            : "No transactions yet on this user's wallets."}
        </p>
      ) : (
        <div className={cn("-mx-5 overflow-x-auto", loading && "opacity-60")}>
          <Table>
            <TableHead>
              <TableRow>
                <TableHeaderCell>When</TableHeaderCell>
                <TableHeaderCell>Service</TableHeaderCell>
                <TableHeaderCell>Direction</TableHeaderCell>
                <TableHeaderCell>Counterparty</TableHeaderCell>
                <TableHeaderCell className="text-right">Amount</TableHeaderCell>
                <TableHeaderCell className="text-right">Service charge</TableHeaderCell>
                <TableHeaderCell>Currency</TableHeaderCell>
                <TableHeaderCell>Txn ID</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {items.map((t) => {
                const isIn = t.direction === "in";
                const isPoints = t.currency === "PTS";
                return (
                  <TableRow key={t.id}>
                    <TableCell className="whitespace-nowrap text-[11px] text-muted-foreground">
                      {formatTimestamp(t.created_at)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-medium">
                      {transactionTypeLabel(t.transaction_type)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <span
                        className={
                          "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold " +
                          (isIn
                            ? "bg-emerald-500/15 text-emerald-700"
                            : "bg-rose-500/15 text-rose-700")
                        }
                      >
                        {isIn ? "IN" : "OUT"}
                      </span>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <CounterpartyCell txn={t} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right font-mono tabular-nums">
                      {isIn ? "+" : "−"}
                      {isPoints ? (
                        <Points amount={t.amount} />
                      ) : (
                        <Money amount={t.amount} currency={t.currency} />
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right font-mono tabular-nums text-muted-foreground">
                      {/* Service charge only applies to financial (non-points) debits. */}
                      {!isPoints && parseFloat(t.fee_amount) > 0 ? (
                        <Money amount={t.fee_amount} currency={t.currency} />
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {t.currency}
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-[11px] text-muted-foreground">
                      {t.reference ?? shortId(t.id, "txn")}
                    </TableCell>
                    <TableCell>
                      <StatusPill status={t.status.toUpperCase()} variant="dense" />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Pager — hidden when a single page holds everything. */}
      {total > 0 ? (
        <div className="flex items-center justify-between pt-1">
          <p className="text-xs text-muted-foreground">
            {from}–{to} of {total}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={!hasPrev || loading}
              className="rounded-md border border-border px-2.5 py-1 text-xs font-medium disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={!hasNext || loading}
              className="rounded-md border border-border px-2.5 py-1 text-xs font-medium disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
