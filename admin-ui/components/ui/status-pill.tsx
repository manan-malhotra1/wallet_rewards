/**
 * <StatusPill> — coloured dot + label for transaction / redemption / rule
 * status. Direct mapping from PRD's status table (docs/04-ui-layouts.md §2.4).
 *
 * Dense variant: dot only (in table cells).
 * Full variant:  dot + label (in detail screens).
 */
import { cn } from "@/lib/utils";

const STATUS_MAP: Record<
  string,
  { label: string; color: string; ring?: string }
> = {
  COMPLETED: { label: "Completed", color: "bg-[--color-success]" },
  PENDING: {
    label: "Pending",
    color: "bg-[--color-warning]",
    ring: "ring-2 ring-[--color-warning]/25 animate-pulse",
  },
  PROCESSING: {
    label: "Processing",
    color: "bg-[--color-warning]",
  },
  FAILED: { label: "Failed", color: "bg-[--color-danger]" },
  REVERSED: { label: "Reversed", color: "bg-[--color-text-3]" },
  MANUAL_REVIEW: {
    label: "Needs review",
    color: "bg-[--color-danger]",
    ring: "ring-2 ring-[--color-danger]/25",
  },
  ACTIVE: { label: "Active", color: "bg-[--color-success]" },
  INACTIVE: { label: "Inactive", color: "bg-[--color-text-3]" },
  DRAFT: { label: "Draft", color: "bg-[--color-text-3]" },
  EXPIRED: { label: "Expired", color: "bg-[--color-text-3]" },
  // Fallback rendered when an unrecognised status arrives.
  UNKNOWN: { label: "Unknown", color: "bg-[--color-text-3]" },
};

export interface StatusPillProps {
  status: string;
  variant?: "dense" | "full";
  className?: string;
}

/**
 * Render a status pill for any transaction-like entity.
 * Uses the colour token matching the status. Dense variant for table rows;
 * full variant for detail screens. Unknown statuses render with the muted
 * fallback colour so the UI never crashes on a new backend status.
 */
export function StatusPill({
  status,
  variant = "dense",
  className,
}: StatusPillProps) {
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
            meta.color,
            meta.ring,
          )}
          aria-hidden="true"
        />
        <span className="text-[12px] text-[--color-text-2]">{meta.label}</span>
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-md bg-[--color-surface-2] px-2 py-1 text-[12px] font-medium text-[--color-text-1]",
        className,
      )}
    >
      <span
        className={cn("block h-2 w-2 rounded-full", meta.color, meta.ring)}
        aria-hidden="true"
      />
      {meta.label}
    </span>
  );
}
