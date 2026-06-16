/**
 * Badge primitive — shadcn/ui shape. Variants map to status semantics.
 *
 * The `tone` prop is kept for backwards-compatibility with existing call
 * sites; map onto the underlying `variant`.
 */
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-md border px-2 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1 [&>svg]:pointer-events-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive transition-[color,box-shadow] overflow-hidden",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive:
          "border-transparent bg-destructive text-white dark:bg-destructive/60",
        outline: "text-foreground",
        success:
          "border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
        warning:
          "border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-300",
        info: "border-transparent bg-sky-500/15 text-sky-700 dark:text-sky-300",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

// Map the legacy `tone` prop to the new variant set so existing call sites
// keep compiling without per-file edits.
const TONE_MAP: Record<string, VariantProps<typeof badgeVariants>["variant"]> = {
  neutral: "secondary",
  brand: "default",
  accent: "info",
  success: "success",
  warning: "warning",
  danger: "destructive",
};

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  tone?: keyof typeof TONE_MAP;
}

export function Badge({ className, variant, tone, ...props }: BadgeProps) {
  const resolved = tone ? TONE_MAP[tone] : variant;
  return (
    <span
      data-slot="badge"
      className={cn(badgeVariants({ variant: resolved }), className)}
      {...props}
    />
  );
}
