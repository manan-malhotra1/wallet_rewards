/**
 * Mobile simulator entry page.
 *
 * Layout: Alice + Bob wallet panes side-by-side, with an event-trigger
 * panel at the bottom. Wallet data fetches in parallel so the slower
 * user's PIN login doesn't block the other. Page is force-dynamic —
 * each load re-fetches both wallets so users see the latest state
 * after a P2P or event fire (which revalidatePath this route).
 */
import { config, type UserKey } from "@/lib/config";
import { getMyWallet, type Wallet } from "@/lib/backend";

import { AirtimeForm } from "./_components/airtime-form";
import { CashInForm } from "./_components/cashin-form";
import { EventTrigger } from "./_components/event-trigger";
import { P2PForm } from "./_components/p2p-form";
import { PartnerApiForm } from "./_components/partner-api-form";
import { WalletPane } from "./_components/wallet-pane";

export const dynamic = "force-dynamic";

async function loadWalletSafely(user: UserKey): Promise<{
  wallet: Wallet | null;
  error: string | null;
}> {
  try {
    const wallet = await getMyWallet(user);
    return { wallet, error: null };
  } catch (err) {
    return {
      wallet: null,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

export default async function HomePage() {
  const [alice, bob, agent, merchant] = await Promise.all([
    loadWalletSafely("alice"),
    loadWalletSafely("bob"),
    loadWalletSafely("agent"),
    loadWalletSafely("merchant"),
  ]);
  const firstError =
    alice.error ?? bob.error ?? agent.error ?? merchant.error;

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <header
        className="flex items-center justify-between rounded-xl px-5 py-4"
        style={{ backgroundColor: "#144989" }}
      >
        <div className="flex items-center gap-3">
          {/* Sasai brand mark on the navy banner (logo forced white). */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/sasai-logo.png"
            alt="Sasai"
            className="select-none"
            style={{ height: 32, width: "auto", filter: "brightness(0) invert(1)" }}
          />
          <span className="hidden rounded-full border border-white/30 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white/80 sm:inline">
            Mobile Simulator
          </span>
        </div>
        <div className="text-right text-[11px] text-white/70">
          backend: <span className="font-mono">{config.backendUrl}</span>
        </div>
      </header>

      {firstError ? (
        <div className="rounded-lg border border-[var(--color-danger)] bg-red-50 px-4 py-3 text-sm text-[var(--color-danger)]">
          <div className="font-semibold">Couldn't load wallet data</div>
          <div className="mt-1 font-mono text-[11px] whitespace-pre-wrap">
            {firstError}
          </div>
          <div className="mt-2 text-xs">
            Check that the backend is running on{" "}
            <span className="font-mono">{config.backendUrl}</span> with{" "}
            <span className="font-mono">SIMULATOR_DEV_MODE=true</span> and
            that <span className="font-mono">make seed</span> has been run
            (the agent + merchant need the latest seed).
          </div>
        </div>
      ) : null}

      <div className="grid gap-5 md:grid-cols-2">
        <WalletPane user="alice" phone={config.users.alice.phone} wallet={alice.wallet}>
          <P2PForm sender="alice" recipient="bob" />
          <AirtimeForm buyer="alice" />
        </WalletPane>
        <WalletPane user="bob" phone={config.users.bob.phone} wallet={bob.wallet}>
          <P2PForm sender="bob" recipient="alice" />
          <AirtimeForm buyer="bob" />
        </WalletPane>
        {/* Agent — cash-in only (funds a customer, earns commission). */}
        <WalletPane user="agent" phone={config.users.agent.phone} wallet={agent.wallet}>
          <CashInForm agent="agent" />
        </WalletPane>
        {/* Airtime merchant — read-only: shows the recharges run against its
            holding account. No action forms. */}
        <WalletPane user="merchant" phone={config.users.merchant.phone} wallet={merchant.wallet} />
      </div>

      {/* Partner external-API panel (fund / withdraw / create user). Targets are
          the configured simulator users, resolved by phone. */}
      <PartnerApiForm
        users={Object.values(config.users).map((u) => ({
          label: u.label,
          phone: u.phone,
        }))}
      />

      <EventTrigger />
    </main>
  );
}
