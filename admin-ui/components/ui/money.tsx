/**
 * <Money> and <Points> — currency-aware amount display.
 *
 * Uses tabular-nums + monospace so columns line up. Negative amounts render
 * with the debit colour; positive with credit.
 */
import { cn, formatAmount } from "@/lib/utils";

export interface MoneyProps {
  amount: string | number;
  currency: string;
  /** Override the colour-by-sign behaviour with an explicit tone. */
  tone?: "neutral" | "credit" | "debit";
  className?: string;
}

/**
 * Currency amount. Defaults to neutral text colour; pass `tone="credit"` or
 * `tone="debit"` to colour the value.
 */
export function Money({ amount, currency, tone = "neutral", className }: MoneyProps) {
  const colourClass =
    tone === "credit"
      ? "text-[--color-credit]"
      : tone === "debit"
        ? "text-[--color-debit]"
        : undefined;
  return (
    <span
      className={cn(
        "tabular font-mono text-[13px] text-[--color-text-1]",
        colourClass,
        className,
      )}
    >
      {currency} {formatAmount(amount, { fractionDigits: 2 })}
    </span>
  );
}

export interface PointsProps {
  amount: string | number;
  className?: string;
}

/**
 * Points amount. Same shape as Money but always renders in the points
 * colour token and with `pts` suffix instead of a currency code.
 */
export function Points({ amount, className }: PointsProps) {
  return (
    <span
      className={cn(
        "tabular font-mono text-[13px] text-[--color-points]",
        className,
      )}
    >
      {formatAmount(amount, { fractionDigits: 0 })} pts
    </span>
  );
}
