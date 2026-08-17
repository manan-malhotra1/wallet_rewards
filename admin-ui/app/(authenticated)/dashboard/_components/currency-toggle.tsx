"use client";

/**
 * Multi-select currency chips.
 *
 * Money metrics render one row/series per selected currency — never summed —
 * so this is the control that decides how many series every money panel draws.
 * At least one currency always stays selected; a tenant with a single currency
 * gets no control at all rather than an undismissable chip.
 */
import type { CurrencyInfo } from "@/lib/api-types";
import { cn } from "@/lib/utils";

interface Props {
  currencies: CurrencyInfo[];
  selected: string[];
  onChange: (codes: string[]) => void;
}

export function CurrencyToggle({ currencies, selected, onChange }: Props) {
  if (currencies.length <= 1) return null;

  function toggle(code: string) {
    const on = selected.includes(code);
    // Deselecting the last one would leave every money panel with nothing to
    // draw, so the final chip is sticky rather than disabled — disabling it
    // would read as "broken" the moment a second currency is deselected.
    if (on && selected.length === 1) return;
    onChange(on ? selected.filter((c) => c !== code) : [...selected, code]);
  }

  return (
    <div className="inline-flex items-center gap-1.5" role="group" aria-label="Currencies">
      {currencies.map((currency) => {
        const active = selected.includes(currency.code);
        return (
          <button
            key={currency.code}
            type="button"
            aria-pressed={active}
            title={`${currency.code} (${currency.symbol})`}
            onClick={() => toggle(currency.code)}
            className={cn(
              "h-[30px] rounded-[9px] border px-[11px] text-[11.5px] font-semibold tracking-[0.04em] transition-colors duration-150",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
              active
                ? "border-transparent bg-primary text-primary-foreground"
                : "bg-chip text-muted-foreground hover:text-foreground",
            )}
          >
            {currency.code}
          </button>
        );
      })}
    </div>
  );
}
