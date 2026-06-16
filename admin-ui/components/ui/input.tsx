/**
 * Input primitive — consistent height + dense padding to match the design
 * tokens. Variants are intentionally minimal; use `className` for outliers.
 */
import * as React from "react";

import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-8 w-full rounded-md border border-[--color-border] bg-[--color-surface-1] px-2.5 text-[13px] text-[--color-text-1] placeholder:text-[--color-text-3]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[--color-brand]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
