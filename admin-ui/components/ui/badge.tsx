/**
 * Badge / Pill component. Compact inline label. Distinct from <StatusPill>
 * which carries semantic status (COMPLETED / PENDING / etc) — Badge is for
 * generic tags (rule type, segment, etc).
 */
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium",
  {
    variants: {
      tone: {
        neutral: "bg-[--color-surface-3] text-[--color-text-2]",
        brand: "bg-[--color-brand]/15 text-[--color-brand]",
        accent: "bg-[--color-accent]/15 text-[--color-accent]",
        success: "bg-[--color-success]/15 text-[--color-success]",
        warning: "bg-[--color-warning]/15 text-[--color-warning]",
        danger: "bg-[--color-danger]/15 text-[--color-danger]",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
