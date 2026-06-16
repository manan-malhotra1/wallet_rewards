/**
 * <EmptyState> — large centred "nothing here yet" surface for list pages.
 * Used both for first-time-empty and filtered-no-results.
 */
import { cn } from "@/lib/utils";

export interface EmptyStateProps {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[--color-border] bg-[--color-surface-1] px-6 py-12 text-center",
        className,
      )}
    >
      {Icon && (
        <div className="rounded-full bg-[--color-surface-2] p-3">
          <Icon className="h-5 w-5 text-[--color-text-2]" />
        </div>
      )}
      <div>
        <h3 className="text-[14px] font-semibold text-[--color-text-1]">{title}</h3>
        {description && (
          <p className="mt-1 max-w-md text-[12px] text-[--color-text-2]">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}
