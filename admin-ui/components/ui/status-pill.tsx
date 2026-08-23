/**
 * <StatusPill> — coloured dot + label for transaction / redemption / rule
 * status. Refreshed to use Sasai brand semantic tokens.
 */
import { cn } from "@/lib/utils";

const STATUS_MAP: Record<
  string,
  { label: string; dot: string; bg: string; text: string; pulse?: boolean }
> = {
  COMPLETED: {
    label: "Completed",
    dot: "bg-emerald-500",
    bg: "bg-emerald-500/10 dark:bg-emerald-500/15",
    text: "text-emerald-700 dark:text-emerald-300",
  },
  PENDING: {
    label: "Pending",
    dot: "bg-amber-500",
    bg: "bg-amber-500/10 dark:bg-amber-500/15",
    text: "text-amber-700 dark:text-amber-300",
    pulse: true,
  },
  PROCESSING: {
    label: "Processing",
    dot: "bg-amber-500",
    bg: "bg-amber-500/10 dark:bg-amber-500/15",
    text: "text-amber-700 dark:text-amber-300",
  },
  FAILED: {
    label: "Failed",
    dot: "bg-red-500",
    bg: "bg-red-500/10 dark:bg-red-500/15",
    text: "text-red-700 dark:text-red-400",
  },
  REVERSED: {
    label: "Reversed",
    dot: "bg-slate-400",
    bg: "bg-muted",
    text: "text-muted-foreground",
  },
  MANUAL_REVIEW: {
    label: "Needs review",
    dot: "bg-red-500",
    bg: "bg-red-500/10 dark:bg-red-500/15",
    text: "text-red-700 dark:text-red-400",
  },
  ACTIVE: {
    label: "Active",
    dot: "bg-emerald-500",
    bg: "bg-emerald-500/10 dark:bg-emerald-500/15",
    text: "text-emerald-700 dark:text-emerald-300",
  },
  INACTIVE: {
    label: "Inactive",
    dot: "bg-slate-400",
    bg: "bg-muted",
    text: "text-muted-foreground",
  },
  SUSPENDED: {
    label: "Suspended",
    dot: "bg-red-500",
    bg: "bg-red-500/10 dark:bg-red-500/15",
    text: "text-red-700 dark:text-red-400",
  },
  // A user type that is no longer assignable but still referenced by existing
  // users and config rows — retired, never deleted (spec D3).
  RETIRED: {
    label: "Retired",
    dot: "bg-slate-400",
    bg: "bg-muted",
    text: "text-muted-foreground",
  },
  DRAFT: {
    label: "Draft",
    dot: "bg-slate-400",
    bg: "bg-muted",
    text: "text-muted-foreground",
  },
  SCHEDULED: {
    label: "Scheduled",
    dot: "bg-amber-500",
    bg: "bg-amber-500/10 dark:bg-amber-500/15",
    text: "text-amber-700 dark:text-amber-300",
  },
  EXPIRED: {
    label: "Expired",
    dot: "bg-slate-400",
    bg: "bg-muted",
    text: "text-muted-foreground",
  },
  // Epic 24 — config change-request lifecycle statuses.
  CHANGES_REQUESTED: {
    label: "Changes requested",
    dot: "bg-amber-500",
    bg: "bg-amber-500/10 dark:bg-amber-500/15",
    text: "text-amber-700 dark:text-amber-300",
  },
  APPLIED: {
    label: "Applied",
    dot: "bg-emerald-500",
    bg: "bg-emerald-500/10 dark:bg-emerald-500/15",
    text: "text-emerald-700 dark:text-emerald-300",
  },
  WITHDRAWN: {
    label: "Withdrawn",
    dot: "bg-slate-400",
    bg: "bg-muted",
    text: "text-muted-foreground",
  },
  UNKNOWN: {
    label: "Unknown",
    dot: "bg-slate-400",
    bg: "bg-muted",
    text: "text-muted-foreground",
  },
};

export interface StatusPillProps {
  status: string;
  variant?: "dense" | "full";
  className?: string;
}

export function StatusPill({ status, variant = "dense", className }: StatusPillProps) {
  const meta = STATUS_MAP[status] ?? STATUS_MAP.UNKNOWN;
  if (variant === "dense") {
    return (
      <span
        title={meta.label}
        className={cn("inline-flex items-center gap-1.5", className)}
      >
        <span
          className={cn(
            "block h-2 w-2 rounded-full",
            meta.dot,
            meta.pulse && "animate-pulse",
          )}
          aria-hidden="true"
        />
        <span className={cn("text-xs", meta.text)}>{meta.label}</span>
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-md px-2 py-0.5 text-xs font-medium",
        meta.bg,
        meta.text,
        className,
      )}
    >
      <span
        className={cn(
          "block h-1.5 w-1.5 rounded-full",
          meta.dot,
          meta.pulse && "animate-pulse",
        )}
        aria-hidden="true"
      />
      {meta.label}
    </span>
  );
}
