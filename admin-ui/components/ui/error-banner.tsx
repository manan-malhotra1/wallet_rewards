/**
 * <ErrorBanner> — inline error surface above a table or form when a
 * server call fails. Keeps the UI rendered (vs throwing).
 */
import { AlertCircle } from "lucide-react";

import { cn } from "@/lib/utils";

export interface ErrorBannerProps {
  title: string;
  description?: string;
  className?: string;
}

export function ErrorBanner({ title, description, className }: ErrorBannerProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-2 rounded-md border border-[--color-danger]/40 bg-[--color-danger]/10 px-3 py-2 text-[12px] text-[--color-danger]",
        className,
      )}
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <div className="font-semibold">{title}</div>
        {description && <div className="text-[11px] opacity-80">{description}</div>}
      </div>
    </div>
  );
}
