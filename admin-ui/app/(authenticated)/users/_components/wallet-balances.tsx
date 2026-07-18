"use client";

/**
 * Horizontal slider of a user's financial-wallet balances — one currency per
 * slide, with dot indicators — so every currency wallet (e.g. ZAR + INR) is
 * shown in the compact KPI card instead of "+N more". Degrades to a single
 * amount when the user has just one wallet.
 */
import { useRef, useState } from "react";

import { Money } from "@/components/ui/money";

/** The minimal wallet shape the slider needs (a financial-wallet account). */
type Wallet = {
  id: string;
  currency: string;
  available_balance: string;
};

export function WalletBalances({ wallets }: { wallets: Wallet[] }) {
  const scroller = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);

  if (wallets.length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }
  if (wallets.length === 1) {
    return <Money amount={wallets[0].available_balance} currency={wallets[0].currency} />;
  }

  /** Track which slide is centred so the matching dot lights up. */
  function onScroll() {
    const el = scroller.current;
    if (!el) return;
    setActive(Math.round(el.scrollLeft / el.clientWidth));
  }

  /** Jump to a wallet when its dot is clicked. */
  function goTo(index: number) {
    const el = scroller.current;
    if (!el) return;
    el.scrollTo({ left: index * el.clientWidth, behavior: "smooth" });
  }

  return (
    <div>
      <div
        ref={scroller}
        onScroll={onScroll}
        className="flex snap-x snap-mandatory overflow-x-auto [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {wallets.map((w) => (
          <div key={w.id} className="w-full flex-none snap-start">
            <Money amount={w.available_balance} currency={w.currency} />
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-1">
        {wallets.map((w, i) => (
          <button
            key={w.id}
            type="button"
            aria-label={`Show ${w.currency} wallet`}
            onClick={() => goTo(i)}
            className={`h-1.5 rounded-full transition-all ${
              i === active ? "w-4 bg-foreground" : "w-1.5 bg-muted-foreground/40"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
