/**
 * Button primitive — variants match the design tokens.
 *
 * Variants:
 *   - default: brand-tinted, used for primary actions
 *   - ghost:   subtle hover, used for secondary actions
 *   - outline: border + transparent bg, used for tertiary actions
 *   - danger:  red, used for destructive actions
 *   - link:    underlined text, used for in-table actions
 *
 * Sizes:
 *   - sm: 28px tall, dense tables
 *   - md: 32px tall, default
 *   - lg: 40px tall, modal CTAs
 */
import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "@radix-ui/react-slot";
import * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[--color-brand] disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-[--color-brand] text-white hover:opacity-90 active:opacity-100",
        ghost:
          "bg-transparent text-[--color-text-1] hover:bg-[--color-surface-2]",
        outline:
          "border border-[--color-border] bg-transparent text-[--color-text-1] hover:bg-[--color-surface-2]",
        danger:
          "bg-[--color-danger] text-white hover:opacity-90",
        link: "text-[--color-accent] underline-offset-2 hover:underline",
      },
      size: {
        sm: "h-7 px-2.5 text-[12px]",
        md: "h-8 px-3 text-[13px]",
        lg: "h-10 px-4 text-[14px]",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: { variant: "default", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

/**
 * Polymorphic button. Pass `asChild` to render the variant styles on a
 * child element (e.g. a Next.js `<Link>`) instead of a `<button>`.
 */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };
