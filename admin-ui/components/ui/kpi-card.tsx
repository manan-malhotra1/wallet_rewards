/**
 * <KpiCard> — the FinOps Studio metric tile.
 *
 * Card with a small icon-tile in the corner, an uppercase metric label,
 * a large tabular number, and an optional subtext + trend indicator.
 */
import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

export interface KpiCardProps {
  label: string;
  value: string | number;
  subtext?: string;
  /** Positive = up, negative = down, 0 = flat. Optional. */
  trend?: number;
  trendLabel?: string;
  icon?: React.ComponentType<{ className?: string }>;
  /** Override the icon tile tint. Defaults to `bg-primary/10` + `text-primary`. */
  iconTone?: "primary" | "emerald" | "amber" | "red" | "sky" | "violet";
  className?: string;
}

const ICON_TONE_BG: Record<NonNullable<KpiCardProps["iconTone"]>, string> = {
  primary: "bg-primary/10 text-primary",
  emerald: "bg-emerald-500/10 text-emerald-500",
  amber: "bg-amber-500/10 text-amber-500",
  red: "bg-red-500/10 text-red-500",
  sky: "bg-sky-500/10 text-sky-500",
  violet: "bg-violet-500/10 text-violet-500",
};

export function KpiCard({
  label,
  value,
  subtext,
  trend,
  trendLabel,
  icon: Icon,
  iconTone = "primary",
  className,
}: KpiCardProps) {
  const trendPositive = trend !== undefined && trend > 0;
  const trendNegative = trend !== undefined && trend < 0;

  return (
    <div
      className={cn(
        "glass-panel rounded-lg p-5 transition-shadow hover:shadow-md",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {label}
          </p>
          <p className="text-2xl font-bold tabular text-foreground">{value}</p>
          {subtext && (
            <p className="mt-0.5 text-xs text-muted-foreground">{subtext}</p>
          )}
        </div>
        {Icon && (
          <div
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
              ICON_TONE_BG[iconTone],
            )}
          >
            <Icon className="h-4 w-4" />
          </div>
        )}
      </div>

      {trend !== undefined && (
        <div className="mt-3 flex items-center gap-1">
          {trendPositive && <TrendingUp className="h-3 w-3 text-emerald-500" />}
          {trendNegative && <TrendingDown className="h-3 w-3 text-red-500" />}
          {trend === 0 && <Minus className="h-3 w-3 text-muted-foreground" />}
          <span
            className={cn(
              "text-xs font-medium",
              trendPositive && "text-emerald-500",
              trendNegative && "text-red-500",
              trend === 0 && "text-muted-foreground",
            )}
          >
            {trend > 0 ? "+" : ""}
            {trend.toFixed(1)}%
          </span>
          {trendLabel && (
            <span className="text-xs text-muted-foreground">{trendLabel}</span>
          )}
        </div>
      )}
    </div>
  );
}
