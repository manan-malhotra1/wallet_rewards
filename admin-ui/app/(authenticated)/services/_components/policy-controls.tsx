/**
 * Shared building blocks for the Services access-policy editor.
 *
 * The policy has two dimensions — WHO (user types) and WHICH CHANNELS may
 * initiate a service. Both the create dialog and the edit-policy dialog render
 * the same toggle-chip group defined here, plus the compact badge summary used
 * in the table. Keeping the labels + chip UI in one place avoids drift between
 * the two surfaces.
 */
"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ServiceChannel, UserType } from "@/lib/api-types";

/** Human-readable labels for the five user types. */
const USER_TYPE_LABELS: Record<UserType, string> = {
  consumer: "Consumer",
  agent: "Agent",
  super_agent: "Super agent",
  merchant: "Merchant",
  head_merchant: "Head merchant",
};

/** Human-readable labels for the six initiation channels. */
const CHANNEL_LABELS: Record<ServiceChannel, string> = {
  web: "Web",
  api: "API",
  mobile: "Mobile",
  ussd: "USSD",
  admin: "Admin",
  system: "System",
};

/**
 * Resolve a display label for any policy value, falling back to the raw code
 * so an unknown value the backend adds later still renders legibly.
 */
export function policyLabel(value: string): string {
  return (
    USER_TYPE_LABELS[value as UserType] ??
    CHANNEL_LABELS[value as ServiceChannel] ??
    value
  );
}

/**
 * A group of toggle chips backing a multi-select. Each chip mirrors its
 * selected state via `aria-pressed` so it is keyboard- and screen-reader
 * friendly (no native shadcn multiselect exists in this repo).
 *
 * @param options The full set of selectable values, in display order.
 * @param selected The currently-selected values.
 * @param onToggle Called with a value when its chip is clicked.
 */
export function ChipGroup({
  options,
  selected,
  onToggle,
  disabled,
  ariaLabel,
}: {
  options: readonly string[];
  selected: string[];
  onToggle: (value: string) => void;
  disabled?: boolean;
  ariaLabel: string;
}) {
  const selectedSet = new Set(selected);
  return (
    <div className="mt-1 flex flex-wrap gap-1.5" role="group" aria-label={ariaLabel}>
      {options.map((value) => {
        const active = selectedSet.has(value);
        return (
          <button
            key={value}
            type="button"
            aria-pressed={active}
            disabled={disabled}
            onClick={() => onToggle(value)}
            className={cn(
              "inline-flex h-7 items-center rounded-full border px-3 text-[12px] font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              "disabled:pointer-events-none disabled:opacity-50",
              active
                ? "border-transparent bg-primary text-primary-foreground"
                : "border-[--color-border] bg-[--color-surface-1] text-[--color-text-2] hover:bg-[--color-surface-2]",
            )}
          >
            {policyLabel(value)}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Compact read-only summary of one policy dimension for the table. Renders
 * "All" when the value is `null` (unrestricted), "None" when it is an empty
 * array (operator-only), otherwise up to `max` value badges with a "+N" spill.
 */
export function PolicySummary({
  values,
  max = 3,
}: {
  values: string[] | null;
  max?: number;
}) {
  if (values === null) {
    return (
      <Badge variant="secondary" className="text-[11px]">
        All
      </Badge>
    );
  }
  if (values.length === 0) {
    return (
      <Badge variant="warning" className="text-[11px]">
        None
      </Badge>
    );
  }
  const shown = values.slice(0, max);
  const extra = values.length - shown.length;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {shown.map((value) => (
        <Badge key={value} variant="outline" className="text-[11px]">
          {policyLabel(value)}
        </Badge>
      ))}
      {extra > 0 && (
        <span className="text-[11px] text-[--color-text-3]">+{extra}</span>
      )}
    </div>
  );
}
