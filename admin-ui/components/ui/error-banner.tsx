/**
 * <ErrorBanner> — inline error surface above a table or form.
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
        "flex items-start gap-3 rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive dark:text-red-400",
        className,
      )}
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <div className="font-semibold">{title}</div>
        {description && <div className="mt-0.5 text-xs opacity-90">{description}</div>}
      </div>
    </div>
  );
}
