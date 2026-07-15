/**
 * <SystemWalletsView> — client container for the System Wallets table.
 *
 * Owns two pieces of client state on top of the server-fetched wallets:
 *  1. A currency checkbox filter (Feature 2) that narrows the rows shown.
 *  2. A reconciliation summary (Feature 1) comparing the sum of bank-mirror
 *     balances against the cash float, per currency — purely informational.
 */
"use client";

import * as React from "react";

import { Money } from "@/components/ui/money";
import { Checkbox } from "@/components/ui/checkbox";
import type { SystemWallet } from "@/lib/api-types";

import { SystemWalletGrid } from "./system-wallet-grid";

/** Sum a list of decimal-string balances into a fixed-2 string. */
function sumBalances(wallets: SystemWallet[]): string {
  const total = wallets.reduce((acc, w) => acc + Number(w.balance), 0);
  return total.toFixed(2);
}

export function SystemWalletsView({
  wallets,
  tenantId,
}: {
  wallets: SystemWallet[];
  tenantId: string;
}) {
  // Distinct currencies across all wallets, stable-sorted for a steady UI.
  const currencies = React.useMemo(
    () => Array.from(new Set(wallets.map((w) => w.currency))).sort(),
    [wallets],
  );

  // All currencies start checked; keys are currency codes.
  const [checked, setChecked] = React.useState<Record<string, boolean>>(() =>
    Object.fromEntries(currencies.map((c) => [c, true])),
  );

  const toggle = (currency: string) =>
    setChecked((prev) => ({ ...prev, [currency]: !prev[currency] }));

  const visibleWallets = wallets.filter((w) => checked[w.currency] ?? true);

  // Reconciliation: bank-mirror total vs cash float, per currency where a
  // mirror or cash float exists. Non-financial mirrors carry no cap; this is
  // an eyeball check for the operator, not an enforced invariant.
  const reconCurrencies = Array.from(
    new Set(
      wallets
        .filter(
          (w) =>
            w.account_type === "operator_adjustment" ||
            w.account_type === "system_cash_inflow",
        )
        .map((w) => w.currency),
    ),
  ).sort();

  return (
    <div className="space-y-4">
      {reconCurrencies.length > 0 ? (
        <div className="rounded-lg border border-[--color-border] bg-[--color-surface-1] px-4 py-3 text-sm text-[--color-text-2]">
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-[--color-text-3]">
            Reconciliation
          </p>
          <div className="space-y-1">
            {reconCurrencies.map((currency) => {
              const mirrorTotal = sumBalances(
                wallets.filter(
                  (w) =>
                    w.account_type === "operator_adjustment" &&
                    w.currency === currency,
                ),
              );
              const cashFloat = sumBalances(
                wallets.filter(
                  (w) =>
                    w.account_type === "system_cash_inflow" &&
                    w.currency === currency,
                ),
              );
              return (
                <p key={currency} className="tabular-nums">
                  Bank mirrors total:{" "}
                  <Money amount={mirrorTotal} currency={currency} /> vs Cash
                  float: <Money amount={cashFloat} currency={currency} />
                </p>
              );
            })}
          </div>
        </div>
      ) : null}

      {currencies.length > 1 ? (
        <div className="flex items-center gap-4">
          <span className="text-[11px] font-medium uppercase tracking-wide text-[--color-text-3]">
            Currency
          </span>
          {currencies.map((currency) => (
            <Checkbox
              key={currency}
              label={currency}
              checked={checked[currency] ?? true}
              onChange={() => toggle(currency)}
            />
          ))}
        </div>
      ) : null}

      <SystemWalletGrid wallets={visibleWallets} tenantId={tenantId} />
    </div>
  );
}
