/**
 * <SystemWalletGrid> — card per system account with balance + actions.
 *
 * Renders the per-row Adjust dialog and Transactions drill-down. Cards
 * are colour-coded by type so float / issuance / fees stand out at a
 * glance.
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Money, Points } from "@/components/ui/money";
import { StatusPill } from "@/components/ui/status-pill";
import { shortId } from "@/lib/utils";
import type { SystemWallet } from "@/lib/api-types";

import { AdjustSystemWalletDialog } from "./adjust-system-wallet-dialog";
import { TransactionsDialog } from "./transactions-dialog";

const TYPE_META: Record<
  string,
  { label: string; icon: React.ComponentType<{ className?: string }>; tone: string }
> = {
  system_cash_inflow: {
    label: "Cash float",
    icon: Banknote,
    tone: "from-emerald-500/15 to-emerald-500/5 border-emerald-500/40",
  },
  system_points_issuance: {
    label: "Points issuance pool",
    icon: Sparkles,
    tone: "from-violet-500/15 to-violet-500/5 border-violet-500/40",
  },
  system_fee_collected: {
    label: "Fees collected",
    icon: Coins,
    tone: "from-amber-500/15 to-amber-500/5 border-amber-500/40",
  },
  provider_redemption_wallet: {
    label: "Provider redemption wallet",
    icon: Wallet,
    tone: "from-sky-500/15 to-sky-500/5 border-sky-500/40",
  },
  operator_adjustment: {
    label: "Operator adjustments",
    icon: PiggyBank,
    tone: "from-slate-500/15 to-slate-500/5 border-slate-500/40",
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
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {wallets.map((w) => {
        const meta = TYPE_META[w.account_type] ?? {
          label: w.account_type,
          icon: Wallet,
          tone: "from-slate-500/10 to-slate-500/5 border-slate-500/30",
        };
        const Icon = meta.icon;
        const isPoints = w.currency === "PTS";
        return (
          <Card
            key={w.id}
            className={`border bg-gradient-to-br ${meta.tone}`}
          >
            <CardHeader className="flex flex-row items-start justify-between gap-2 pb-2">
              <div className="flex items-center gap-2">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-card shadow-sm">
                  <Icon className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <CardTitle className="text-sm">{meta.label}</CardTitle>
                  <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                    {shortId(w.id, "acc")}
                  </div>
                </div>
              </div>
              <StatusPill status={w.status.toUpperCase()} variant="dense" />
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="font-mono text-2xl font-semibold tabular-nums">
                {isPoints ? (
                  <Points amount={w.balance} />
                ) : (
                  <Money amount={w.balance} currency={w.currency} />
                )}
              </div>
              <div className="flex items-center gap-2">
                <AdjustSystemWalletDialog
                  account={w}
                  tenantId={tenantId}
                  trigger={
                    <Button variant="outline" size="sm" className="gap-1.5">
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
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
