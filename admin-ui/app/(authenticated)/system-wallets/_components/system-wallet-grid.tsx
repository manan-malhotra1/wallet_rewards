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
  HandCoins,
  Info,
  Landmark,
  Percent,
  Receipt,
  ScrollText,
  Smartphone,
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
import { Tooltip } from "@/components/ui/tooltip";
import type { SystemWallet } from "@/lib/api-types";

import { AdjustSystemWalletDialog } from "./adjust-system-wallet-dialog";
import { TransactionsDialog } from "./transactions-dialog";

// Friendly name + a tooltip explaining what each platform account is for.
const TYPE_META: Record<
  string,
  {
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    description: string;
  }
> = {
  system_cash_inflow: {
    label: "Cash float",
    icon: Banknote,
    description:
      "The platform's operating cash. Funding a user wallet debits this float; withdrawals return to it.",
  },
  system_points_issuance: {
    label: "Points issuance pool",
    icon: Sparkles,
    description:
      "Master source of reward points. Its balance trends negative — that figure is total points outstanding.",
  },
  system_fee_collected: {
    label: "Fees collected",
    icon: Coins,
    description: "Where every service-charge fee is collected.",
  },
  provider_redemption_wallet: {
    label: "Provider redemption wallet",
    icon: Wallet,
    description: "Points settled to a redemption provider (e.g. voucher partner).",
  },
  operator_adjustment: {
    label: "Bank Mirror Account",
    icon: Landmark,
    description:
      "Mirrors real bank movements. The counter-leg for admin fund/withdraw and operator-float adjustments so the ledger stays balanced.",
  },
  commission: {
    label: "Commission Funded Wallet",
    icon: HandCoins,
    description:
      "Platform-funded pool from which agent commissions are paid. Debited when an agent earns a commission (may run negative).",
  },
  tax_service_collected: {
    label: "Tax Collected on Service Charges",
    icon: Receipt,
    description: "Tax charged on service fees is collected here.",
  },
  tax_commission_collected: {
    label: "Tax Collected on Commissions",
    icon: Percent,
    description: "Tax charged on agent commissions is collected here.",
  },
  airtime_merchant_holding: {
    label: "Airtime merchant holding",
    icon: Smartphone,
    description: "Escrow for airtime recharges pending settlement with the merchant/MNO.",
  },
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
              description: "",
            };
            const Icon = meta.icon;
            const isPoints = w.currency === "PTS";
            return (
              <TableRow key={w.id}>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Icon className="h-3.5 w-3.5 text-[--color-text-3]" aria-hidden="true" />
                    <span className="font-medium">{meta.label}</span>
                    {meta.description ? (
                      <Tooltip content={meta.description}>
                        <button
                          type="button"
                          aria-label={`About ${meta.label}`}
                          className="text-[--color-text-3] hover:text-[--color-text-1]"
                        >
                          <Info className="h-3.5 w-3.5" />
                        </button>
                      </Tooltip>
                    ) : null}
                  </div>
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
