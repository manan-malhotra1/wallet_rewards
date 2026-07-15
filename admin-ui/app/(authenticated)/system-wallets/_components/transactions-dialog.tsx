/**
 * <TransactionsDialog> — drill-down list of recent transactions touching
 * the account. Loaded lazily on first open so the page doesn't pre-fetch
 * every account's full history.
 */
"use client";

import { ArrowDownLeft, ArrowUpRight } from "lucide-react";
import * as React from "react";

import { loadSystemWalletTransactionsAction } from "@/app/(authenticated)/system-wallets/_actions";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ErrorBanner } from "@/components/ui/error-banner";
import { StatusPill } from "@/components/ui/status-pill";
import { formatTimestamp, shortId } from "@/lib/utils";
import type { SystemWallet, SystemWalletTransaction } from "@/lib/api-types";

export function TransactionsDialog({
  account,
  tenantId,
  trigger,
}: {
  account: SystemWallet;
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [rows, setRows] = React.useState<SystemWalletTransaction[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setRows(null);
    setError(null);
    (async () => {
      const result = await loadSystemWalletTransactionsAction(account.id, tenantId);
      if (result.ok) setRows(result.rows);
      else setError(result.message);
    })();
  }, [open, account.id, tenantId]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent
        className="flex max-h-[85vh] w-[min(96vw,1100px)] max-w-none flex-col overflow-hidden sm:max-w-none"
      >
        <DialogHeader>
          <DialogTitle>Recent transactions</DialogTitle>
          <DialogDescription>
            Latest 50 ledger entries touching {account.account_type} ({account.currency}).
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-auto rounded-md border">
          {error ? (
            <div className="p-4">
              <ErrorBanner title="Couldn't load transactions" description={error} />
            </div>
          ) : rows === null ? (
            <div className="p-6 text-center text-sm text-muted-foreground">
              Loading…
            </div>
          ) : rows.length === 0 ? (
            <div className="p-6 text-center text-sm text-muted-foreground">
              No transactions on this account yet.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="whitespace-nowrap px-3 py-2 text-left">When</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left">Type</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left">Direction</th>
                  <th className="whitespace-nowrap px-3 py-2 text-right">Amount</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left">Txn ID</th>
                  <th className="whitespace-nowrap px-3 py-2 text-left">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const isCredit = r.entry_type === "CREDIT";
                  return (
                    <tr key={r.transaction_id} className="border-t">
                      <td className="whitespace-nowrap px-3 py-2 text-[11px] text-muted-foreground">
                        {formatTimestamp(r.created_at)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px]">
                        {r.transaction_type}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <span
                          className={
                            "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold " +
                            (isCredit
                              ? "bg-emerald-500/15 text-emerald-700"
                              : "bg-rose-500/15 text-rose-700")
                          }
                        >
                          {isCredit ? (
                            <ArrowDownLeft className="h-3 w-3" />
                          ) : (
                            <ArrowUpRight className="h-3 w-3" />
                          )}
                          {r.entry_type}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right font-mono tabular-nums">
                        {isCredit ? "+" : "−"}
                        {r.entry_amount} {r.currency}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px] text-muted-foreground">
                        {r.reference ?? shortId(r.transaction_id, "txn")}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <StatusPill status={r.status} variant="dense" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
