/**
 * Label primitive — wraps a form control's text in semantic <label>.
 * Aligned with our 12px caption type token. Use `htmlFor` to associate.
 */
import * as React from "react";

import { cn } from "@/lib/utils";

export type LabelProps = React.LabelHTMLAttributes<HTMLLabelElement>;

export const Label = React.forwardRef<HTMLLabelElement, LabelProps>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn(
        "text-[12px] font-medium text-[--color-text-2]",
        className,
      )}
      {...props}
    />
  ),
);
Label.displayName = "Label";
