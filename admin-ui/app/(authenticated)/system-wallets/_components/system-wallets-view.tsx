/**
 * <SystemWalletsView> — client container for the System Wallets page.
 *
 * Owns a currency checkbox filter, and splits the accounts into two panes:
 * Bank mirrors (operator_adjustment — several, operator-named) shown ABOVE the
 * platform's other system accounts. No reconciliation figure is shown — the
 * mirrors and the cash float never match (the float distributes to users).
 */
"use client";

import * as React from "react";

import { Checkbox } from "@/components/ui/checkbox";
import type { SystemWallet } from "@/lib/api-types";

import { SystemWalletGrid } from "./system-wallet-grid";

const MIRROR_TYPE = "operator_adjustment";

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
  const mirrors = visibleWallets.filter((w) => w.account_type === MIRROR_TYPE);
  const others = visibleWallets.filter((w) => w.account_type !== MIRROR_TYPE);

  return (
    <div className="space-y-6">
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

      {mirrors.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-[11px] font-medium uppercase tracking-wide text-[--color-text-3]">
            Bank mirrors
          </h2>
          {/* Mirrors can be the counter-leg for adjusting each other. */}
          <SystemWalletGrid wallets={mirrors} mirrors={mirrors} tenantId={tenantId} />
        </section>
      ) : null}

      <section className="space-y-2">
        {mirrors.length > 0 ? (
          <h2 className="text-[11px] font-medium uppercase tracking-wide text-[--color-text-3]">
            System accounts
          </h2>
        ) : null}
        <SystemWalletGrid wallets={others} mirrors={mirrors} tenantId={tenantId} />
      </section>
    </div>
  );
}
