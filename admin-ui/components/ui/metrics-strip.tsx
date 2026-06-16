/**
 * <MetricsStrip> — horizontal strip of inline KPIs separated by vertical
 * dividers. Mirrors FinOps Studio's `Health metrics strip`.
 *
 * Each entry is a small icon tile + uppercase label + tabular bold value.
 * Use sparingly — strong visual anchor at the top of operations pages.
 */
import * as React from "react";

import { cn } from "@/lib/utils";

export interface MetricsStripItem {
  label: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
  iconTone?: "primary" | "emerald" | "amber" | "red" | "sky" | "violet";
  /** Override the value's text colour (e.g. emerald when "all clear"). */
  valueTone?: "neutral" | "emerald" | "amber" | "red";
}

const ICON_TONE_BG: Record<NonNullable<MetricsStripItem["iconTone"]>, string> = {
  primary: "bg-primary/10 text-primary",
  emerald: "bg-emerald-500/10 text-emerald-500",
  amber: "bg-amber-500/10 text-amber-500",
  red: "bg-red-500/10 text-red-500",
  sky: "bg-sky-500/10 text-sky-500",
  violet: "bg-violet-500/10 text-violet-500",
};

const VALUE_TONE: Record<NonNullable<MetricsStripItem["valueTone"]>, string> = {
  neutral: "text-foreground",
  emerald: "text-emerald-500",
  amber: "text-amber-500",
  red: "text-red-500",
};

export function MetricsStrip({ items }: { items: MetricsStripItem[] }) {
  return (
    <div className="grid grid-cols-2 divide-x divide-y divide-border border-b bg-muted/30 md:grid-cols-4 md:divide-y-0">
      {items.map((item, idx) => (
        <div key={idx} className="flex items-center gap-3 px-4 py-3">
          <div
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-md",
              ICON_TONE_BG[item.iconTone ?? "primary"],
            )}
          >
            <item.icon className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {item.label}
            </p>
            <p
              className={cn(
                "text-base font-bold tabular leading-tight",
                VALUE_TONE[item.valueTone ?? "neutral"],
              )}
            >
              {item.value}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
