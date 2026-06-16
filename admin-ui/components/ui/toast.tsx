/**
 * Toast notifications — bottom-right stack. Used for action confirmations
 * and inline error surfacing.
 *
 * Backed by Radix Toast. We expose a `<Toaster>` mount + a `useToast`
 * imperative hook. Three slots max, FIFO.
 */
"use client";

import * as ToastPrimitive from "@radix-ui/react-toast";
import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

type Toast = {
  id: string;
  title: string;
  description?: string;
  variant?: "default" | "danger";
};

const ToastContext = React.createContext<{
  toast: (input: Omit<Toast, "id">) => void;
} | null>(null);

/**
 * Imperative toast trigger — usable from client components and server
 * action results that hand a message back via `useFormState`.
 */
export function useToast() {
  const ctx = React.useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <Toaster>");
  return ctx;
}

/**
 * Mount once at the root layout. Provides the imperative `useToast` API and
 * renders the visible stack of in-flight toasts.
 */
export function Toaster() {
  const [toasts, setToasts] = React.useState<Toast[]>([]);

  const toast = React.useCallback((input: Omit<Toast, "id">) => {
    const id = crypto.randomUUID();
    setToasts((current) => [...current.slice(-2), { id, ...input }]);
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      <ToastPrimitive.Provider swipeDirection="right" duration={5000}>
        {toasts.map((t) => (
          <ToastPrimitive.Root
            key={t.id}
            onOpenChange={(open) => {
              if (!open) {
                setToasts((current) => current.filter((toast) => toast.id !== t.id));
              }
            }}
            className={cn(
              "rounded-md border border-[--color-border] bg-[--color-surface-1] p-3 shadow-xl",
              "data-[state=open]:animate-in data-[state=closed]:animate-out",
              "data-[swipe=move]:translate-x-[var(--radix-toast-swipe-move-x)]",
              "data-[swipe=cancel]:translate-x-0",
              t.variant === "danger" && "border-[--color-danger]/40",
            )}
          >
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <ToastPrimitive.Title className="text-[13px] font-semibold text-[--color-text-1]">
                  {t.title}
                </ToastPrimitive.Title>
                {t.description && (
                  <ToastPrimitive.Description className="mt-1 text-[12px] text-[--color-text-2]">
                    {t.description}
                  </ToastPrimitive.Description>
                )}
              </div>
              <ToastPrimitive.Close
                className="rounded p-0.5 text-[--color-text-2] opacity-70 transition-opacity hover:opacity-100"
                aria-label="Dismiss"
              >
                <X className="h-4 w-4" />
              </ToastPrimitive.Close>
            </div>
          </ToastPrimitive.Root>
        ))}
        <ToastPrimitive.Viewport className="fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}
