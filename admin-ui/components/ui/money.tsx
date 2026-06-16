/**
 * <Money> + <Points> — currency-aware amount display with semantic tokens.
 */
import { cn, formatAmount } from "@/lib/utils";

export interface MoneyProps {
  amount: string | number;
  currency: string;
  tone?: "neutral" | "credit" | "debit";
  className?: string;
}

export function Money({ amount, currency, tone = "neutral", className }: MoneyProps) {
  const toneClass =
    tone === "credit"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "debit"
        ? "text-red-600 dark:text-red-400"
        : undefined;
  return (
    <span
      className={cn(
        "tabular font-mono text-sm text-foreground",
        toneClass,
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

export function Points({ amount, className }: PointsProps) {
  return (
    <span className={cn("tabular font-mono text-sm text-amber-600 dark:text-amber-400", className)}>
      {formatAmount(amount, { fractionDigits: 0 })} pts
    </span>
  );
}
