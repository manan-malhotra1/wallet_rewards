/**
 * <WalletLimitsTable> — per-(tenant, currency) financial-wallet limits:
 * a max-balance ceiling + cumulative send/receive caps (daily/weekly/monthly).
 * Inline delete via server action; create through the dialog.
 */
"use client";

import { Trash2 } from "lucide-react";
import * as React from "react";

import { deleteWalletLimitConfigAction } from "@/app/(authenticated)/limits/_actions";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import type { WalletLimitConfig } from "@/lib/api-types";

const WINDOWS = [
  ["D", "daily"],
  ["W", "weekly"],
  ["M", "monthly"],
] as const;

/** Compact one-line "D 5×/1000 · W —/5000" summary for one direction's caps. */
function capsSummary(cfg: WalletLimitConfig, dir: "send" | "receive"): string {
  const parts: string[] = [];
  for (const [short, win] of WINDOWS) {
    const count = cfg[`${dir}_${win}_count_cap` as keyof WalletLimitConfig];
    const value = cfg[`${dir}_${win}_value_cap` as keyof WalletLimitConfig];
    if (count != null || value != null) {
      parts.push(`${short} ${count ?? "—"}× / ${value ?? "—"}`);
    }
  }
  return parts.length ? parts.join("  ·  ") : "—";
}

export function WalletLimitsTable({
  configs,
  tenantId,
}: {
  configs: WalletLimitConfig[];
  tenantId: string;
}) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  const onDelete = async (id: string) => {
    setPending(id);
    const result = await deleteWalletLimitConfigAction(id, tenantId);
    setPending(null);
    if (result.ok) {
      toast({ title: "Wallet limit deleted" });
    } else {
      toast({
        title: "Couldn't delete",
        description: `${result.errorCode}: ${result.message}`,
        variant: "danger",
      });
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell className="text-right">Max balance</TableHeaderCell>
            <TableHeaderCell>Send caps (count / value)</TableHeaderCell>
            <TableHeaderCell>Receive caps (count / value)</TableHeaderCell>
            <TableHeaderCell className="w-[40px]"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {configs.map((cfg) => (
            <TableRow key={cfg.id}>
              <TableCell className="font-mono text-xs">{cfg.currency}</TableCell>
              <TableCell className="text-right font-mono">
                {cfg.max_balance ?? "—"}
              </TableCell>
              <TableCell className="font-mono text-[11px] text-muted-foreground">
                {capsSummary(cfg, "send")}
              </TableCell>
              <TableCell className="font-mono text-[11px] text-muted-foreground">
                {capsSummary(cfg, "receive")}
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Delete wallet limit"
                  disabled={pending === cfg.id}
                  onClick={() => onDelete(cfg.id)}
                >
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
