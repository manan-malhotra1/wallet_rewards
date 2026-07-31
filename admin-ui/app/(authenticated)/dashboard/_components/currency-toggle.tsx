"use client";

/**
 * Multi-select currency chips. Money metrics render one line/series per
 * selected currency — never summed. At least one currency stays selected.
 */
import { cn } from "@/lib/utils";
import type { CurrencyInfo } from "@/lib/api-types";

interface Props {
  currencies: CurrencyInfo[];
  selected: string[];
  onChange: (codes: string[]) => void;
}

export function CurrencyToggle({ currencies, selected, onChange }: Props) {
  if (currencies.length <= 1) return null; // nothing to toggle for a single-currency tenant
  function toggle(code: string) {
    const on = selected.includes(code);
    // keep at least one selected
    if (on && selected.length === 1) return;
    onChange(on ? selected.filter((c) => c !== code) : [...selected, code]);
  }
  return (
    <div className="inline-flex items-center gap-1 rounded-md border bg-card p-0.5" role="group" aria-label="Currencies">
      {currencies.map((c) => {
        const active = selected.includes(c.code);
        return (
          <button
            key={c.code}
            type="button"
            aria-pressed={active}
            onClick={() => toggle(c.code)}
            className={cn(
              "rounded px-2.5 py-1 text-xs font-medium transition-colors",
              active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {c.code}
          </button>
        );
      })}
    </div>
  );
}
