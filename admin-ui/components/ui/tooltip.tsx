/**
 * <Tooltip> — thin Radix wrapper. Mount <TooltipProvider> once high in
 * the tree (the authenticated layout) and use <Tooltip> at the leaves.
 */
"use client";

import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import * as React from "react";

import { cn } from "@/lib/utils";

export const TooltipProvider = TooltipPrimitive.Provider;
export const TooltipRoot = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "glass-overlay z-50 max-w-sm rounded-md px-3 py-2 text-xs text-popover-foreground",
        "animate-in fade-in-0 zoom-in-95",
        className,
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
));
TooltipContent.displayName = "TooltipContent";

/**
 * One-shot helper — wraps a trigger element in a tooltip showing `content`.
 * Use when you just want hover-help on a single element.
 */
export function Tooltip({
  content,
  children,
  delayDuration = 200,
}: {
  content: React.ReactNode;
  children: React.ReactNode;
  delayDuration?: number;
}) {
  return (
    <TooltipRoot delayDuration={delayDuration}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>{content}</TooltipContent>
    </TooltipRoot>
  );
}
