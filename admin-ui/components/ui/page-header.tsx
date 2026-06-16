/**
 * <PageHeader> — top of every page. Title + optional subtitle + actions.
 * Keeps spacing consistent across the admin UI.
 */
import { cn } from "@/lib/utils";

export interface PageHeaderProps {
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}

export function PageHeader({ title, subtitle, actions, className }: PageHeaderProps) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-end justify-between gap-3 border-b border-[--color-border] px-6 py-4",
        className,
      )}
    >
      <div>
        <h1 className="text-[20px] font-semibold text-[--color-text-1]">{title}</h1>
        {subtitle && (
          <p className="mt-0.5 text-[12px] text-[--color-text-3]">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
