/**
 * Toast notifications — backed by sonner (matches FinOps Studio).
 *
 * Two exports for backward compatibility with existing call sites:
 *   - `<Toaster>` — render once at the root layout.
 *   - `useToast()` — imperative shim: returns `{ toast }` that wraps sonner
 *     so existing components (`useToast()` + `toast({title, description})`)
 *     keep working.
 */
"use client";

import { useTheme } from "next-themes";
import { Toaster as SonnerToaster, toast as sonnerToast } from "sonner";

export interface ToastInput {
  title: string;
  description?: string;
  variant?: "default" | "danger";
}

/**
 * Mount once at the root layout — sonner needs its viewport in the DOM.
 * Picks up the active theme via next-themes so dark mode renders correctly.
 */
export function Toaster({ children }: { children?: React.ReactNode }) {
  const { theme = "system" } = useTheme();
  return (
    <>
      {children}
      <SonnerToaster
        theme={theme as "light" | "dark" | "system"}
        position="bottom-right"
        toastOptions={{
          classNames: {
            toast:
              "group toast glass-overlay group-[.toaster]:text-foreground",
            description: "group-[.toast]:text-muted-foreground",
            actionButton:
              "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
            cancelButton:
              "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
          },
        }}
      />
    </>
  );
}

/**
 * Imperative hook compatible with the prior `useToast()` API. Forwards to
 * sonner's `toast()` so call sites don't need changes.
 */
export function useToast() {
  return {
    toast: (input: ToastInput) => {
      if (input.variant === "danger") {
        sonnerToast.error(input.title, { description: input.description });
      } else {
        sonnerToast(input.title, { description: input.description });
      }
    },
  };
}
