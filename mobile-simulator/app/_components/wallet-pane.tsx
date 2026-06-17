/**
 * <WalletPane> — one user's "mobile" view: header, balances per
 * account, recent transactions, plus a Send button row (handled by
 * the parent's <P2PForm>).
 *
 * Pure server component — receives the fetched Wallet payload from
 * the parent so the data is fetched in parallel.
 */
import { Phone, Wallet as WalletIcon } from "lucide-react";

import type { Wallet } from "@/lib/backend";
import type { UserKey } from "@/lib/config";

function formatAmount(value: string, currency: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  const fractionDigits = currency === "PTS" ? 0 : 2;
  return n.toLocaleString(undefined, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export function WalletPane({
  user,
  phone,
  wallet,
  children,
}: {
  user: UserKey;
  phone: string;
  wallet: Wallet | null;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-[var(--color-border)] bg-white p-5 shadow-sm">
      <header className="flex items-center justify-between gap-3 border-b border-[var(--color-border)] pb-4">
        <div>
          <div className="text-lg font-semibold capitalize text-[var(--color-fg)]">
            {wallet?.first_name ?? user}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-[var(--color-fg-muted)]">
            <Phone className="h-3 w-3" /> {phone}
          </div>
        </div>
        <div className="rounded-full bg-[var(--color-brand)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-white">
          Sasai Wallet
        </div>
      </header>

      <section className="grid gap-2">
        {wallet?.accounts.length ? (
          wallet.accounts.map((acct) => (
            <div
              key={acct.id}
              className="flex items-center justify-between rounded-xl border border-[var(--color-border)] bg-[var(--color-bg)] px-4 py-3"
            >
              <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-[var(--color-fg-muted)]">
                <WalletIcon className="h-3.5 w-3.5" />
                {acct.account_type.replaceAll("_", " ")}
              </div>
              <div className="font-mono text-lg font-semibold tabular-nums text-[var(--color-fg)]">
                {formatAmount(acct.balance, acct.currency)}{" "}
                <span className="ml-1 text-xs font-normal text-[var(--color-fg-muted)]">
                  {acct.currency}
                </span>
              </div>
            </div>
          ))
        ) : (
          <div className="rounded-xl border border-dashed border-[var(--color-border)] bg-[var(--color-bg)] px-4 py-6 text-center text-sm text-[var(--color-fg-muted)]">
            No accounts yet.
          </div>
        )}
      </section>

      <section>
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-fg-muted)]">
          Recent activity
        </div>
        {wallet?.recent_transactions.length ? (
          <ul className="flex flex-col gap-1.5">
            {wallet.recent_transactions.map((txn) => (
              <li
                key={txn.id}
                className="flex items-center justify-between rounded-lg border border-[var(--color-border)] px-3 py-2 text-sm"
              >
                <div>
                  <div className="font-medium capitalize text-[var(--color-fg)]">
                    {txn.transaction_type.replaceAll("_", " ")}
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
        ) : (
          <div className="rounded-lg border border-dashed border-[var(--color-border)] px-4 py-3 text-xs text-[var(--color-fg-muted)]">
            No transactions yet.
          </div>
        )}
      </section>

      {children ? <div className="pt-1">{children}</div> : null}
    </div>
  );
}
