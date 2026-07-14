/**
 * Checkbox primitive — a labelled boolean toggle built on a native
 * `<input type="checkbox">` (no Radix checkbox dependency in this repo).
 * Styling mirrors input.tsx / select.tsx (border-input, focus ring, brand
 * accent). Use for opt-in flags such as `fee_inclusive`.
 */
"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface CheckboxProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> {
  /** Optional label rendered to the right of the box. */
  label?: React.ReactNode;
}

export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, id, ...props }, ref) => {
    const generated = React.useId();
    const inputId = id ?? generated;
    return (
      <label
        htmlFor={inputId}
        className={cn(
          "inline-flex items-center gap-2 text-sm text-foreground select-none",
          props.disabled && "cursor-not-allowed opacity-60",
          className,
        )}
      >
        <input
          ref={ref}
          id={inputId}
          type="checkbox"
          data-slot="checkbox"
          className={cn(
            "border-input bg-background text-primary size-4 shrink-0 rounded-[4px] border shadow-xs transition-[color,box-shadow] outline-none",
            "accent-primary focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]",
            "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
          )}
          {...props}
        />
        {label != null && <span>{label}</span>}
      </label>
    );
  },
);
Checkbox.displayName = "Checkbox";
