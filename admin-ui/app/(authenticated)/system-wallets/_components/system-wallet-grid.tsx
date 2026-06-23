/**
 * <SystemWalletGrid> — table of system accounts with balance + actions.
 *
 * Despite the legacy "Grid" name, this is now a dense table — operators
 * scan many accounts at once and need columns to line up. Per-row Adjust
 * and Transactions actions sit at the right edge.
 */
"use client";

import {
  Banknote,
  Coins,
  PiggyBank,
  ScrollText,
  Sparkles,
  Wallet,
} from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Money, Points } from "@/components/ui/money";
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { shortId } from "@/lib/utils";
import type { SystemWallet } from "@/lib/api-types";

import { AdjustSystemWalletDialog } from "./adjust-system-wallet-dialog";
import { TransactionsDialog } from "./transactions-dialog";

const TYPE_META: Record<
  string,
  { label: string; icon: React.ComponentType<{ className?: string }> }
> = {
  system_cash_inflow: { label: "Cash float", icon: Banknote },
  system_points_issuance: { label: "Points issuance pool", icon: Sparkles },
  system_fee_collected: { label: "Fees collected", icon: Coins },
  provider_redemption_wallet: { label: "Provider redemption wallet", icon: Wallet },
  operator_adjustment: { label: "Operator adjustments", icon: PiggyBank },
};

export function SystemWalletGrid({
  wallets,
  tenantId,
}: {
  wallets: SystemWallet[];
  tenantId: string;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface-1]">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Account</TableHeaderCell>
            <TableHeaderCell>ID</TableHeaderCell>
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell className="text-right">Balance</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell className="text-right">Actions</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {wallets.map((w) => {
            const meta = TYPE_META[w.account_type] ?? {
              label: w.account_type,
              icon: Wallet,
            };
            const Icon = meta.icon;
            const isPoints = w.currency === "PTS";
            return (
              <TableRow key={w.id}>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Icon className="h-3.5 w-3.5 text-[--color-text-3]" aria-hidden="true" />
                    <span className="font-medium">{meta.label}</span>
                  </div>
                </TableCell>
                <TableCell className="font-mono text-[11px] text-[--color-text-3]">
                  {shortId(w.id, "acc")}
                </TableCell>
                <TableCell className="font-mono text-[12px]">{w.currency}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {isPoints ? (
                    <Points amount={w.balance} />
                  ) : (
                    <Money amount={w.balance} currency={w.currency} />
                  )}
                </TableCell>
                <TableCell>
                  <StatusPill status={w.status.toUpperCase()} variant="dense" />
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    <AdjustSystemWalletDialog
                      account={w}
                      tenantId={tenantId}
                      trigger={
                        <Button variant="ghost" size="sm" className="gap-1.5">
                          <Coins className="h-3.5 w-3.5" />
                          Adjust
                        </Button>
                      }
                    />
                    <TransactionsDialog
                      account={w}
                      tenantId={tenantId}
                      trigger={
                        <Button variant="ghost" size="sm" className="gap-1.5">
                          <ScrollText className="h-3.5 w-3.5" />
                          Transactions
                        </Button>
                      }
                    />
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
