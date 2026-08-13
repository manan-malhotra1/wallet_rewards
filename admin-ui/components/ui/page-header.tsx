/**
 * <PageHeader> — top-of-page title bar with optional subtitle + actions.
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
    // border idiom: see sidebar.tsx
    <div
      className={cn(
        "glass-panel rounded-none border-0 border-b flex flex-wrap items-end justify-between gap-4 px-6 py-5",
        className,
      )}
    >
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
        {subtitle && (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
