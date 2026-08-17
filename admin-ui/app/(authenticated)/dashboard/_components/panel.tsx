/**
 * Dashboard surface primitives.
 *
 * The redesign layers depth instead of drawing boxes: a frosted `.glass-panel`
 * carrying a hairline top highlight and a long soft shadow, with chart plots
 * recessed into a subtler inset surface. These wrappers keep that recipe in one
 * place so twelve panels can't drift apart.
 *
 * Deliberately free of hooks and `"use client"` so the server-rendered
 * attention strip can use the same surfaces as the interactive client shell.
 */
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Shared elevation: inset hairline along the top edge + a long ambient shadow.
 * Exported so the KPI tiles get the identical resting elevation without
 * restating the shadow (and drifting from it on the next tweak).
 */
export const PANEL_ELEVATION =
  "shadow-[inset_0_1px_0_var(--hairline-top),0_18px_40px_-22px_rgba(0,0,0,0.55)]";

/**
 * A frosted content card — the dashboard's primary surface.
 *
 * Uses `.glass-panel` (so per-tenant tint, blur and the reduced-transparency
 * fallback all still apply) and overrides only the shadow, which Tailwind's
 * utility layer is allowed to do over `@layer components`.
 */
export function Panel({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("glass-panel rounded-[18px] p-5", PANEL_ELEVATION, className)} {...props}>
      {children}
    </div>
  );
}

/** A smaller-radius variant for the dense tile rows (KPIs, mini stats, liquidity). */
export function TilePanel({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("glass-panel rounded-[14px] p-4", PANEL_ELEVATION, className)} {...props}>
      {children}
    </div>
  );
}

/**
 * A section eyebrow: quiet uppercase label over a hairline that fades out.
 *
 * The rule is a background gradient rather than a border so it can dissolve to
 * transparent — a full-width border under every section reads as a table.
 */
export function SectionHeading({ title, hint }: { title: string; hint?: string }) {
  return (
    <div
      className="mb-3.5 flex items-baseline gap-3 bg-[linear-gradient(to_right,var(--border),transparent_62%)] bg-[length:100%_1px] bg-left-bottom bg-no-repeat pb-2"
    >
      <h2 className="text-[10.5px] font-semibold tracking-[0.13em] text-muted-foreground uppercase">
        {title}
      </h2>
      {hint ? <span className="text-[11px] text-muted-foreground/80">{hint}</span> : null}
    </div>
  );
}

/** A panel's title + one-line explanation of what the figures mean. */
export function PanelHeading({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold tracking-[-0.01em] text-foreground">{title}</h3>
        {subtitle ? (
          <span className="text-[11.5px] text-muted-foreground">{subtitle}</span>
        ) : null}
      </div>
      {action}
    </div>
  );
}

/**
 * The recessed surface a chart is drawn on.
 *
 * Tint + inset hairline only, never a blur: `.glass-panel` above it is already
 * a backdrop-filter, and nesting a second one produces the double-blur
 * artifact called out in the glassmorphism spec.
 */
export function InsetPlot({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "relative rounded-[14px] bg-surface-inset shadow-[inset_0_1px_0_var(--hairline-top)]",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

/**
 * The empty counterpart to {@link InsetPlot}: a dashed plot-shaped placeholder.
 *
 * Shaped like the chart it replaces so a quiet range reads as "no data here",
 * not as a panel that failed to render.
 */
export function EmptyPlot({
  message,
  icon,
  className,
}: {
  message: string;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2.5 rounded-[14px] border border-dashed border-border-dash bg-surface-inset",
        className,
      )}
    >
      {icon ? <span className="text-muted-foreground">{icon}</span> : null}
      <span className="text-[12.5px] text-muted-foreground">{message}</span>
    </div>
  );
}

/**
 * An inline "this panel's data didn't load" notice.
 *
 * `loadDashboardData` settles each dataset independently, so one failed fetch
 * must degrade to a notice inside its own panel — never a blank card, and never
 * a whole-page error. `action` carries the caller's retry control so this stays
 * a server-safe presentational component.
 */
export function PanelNotice({
  message,
  action,
  className,
}: {
  message: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      role="status"
      className={cn(
        "flex items-center gap-2.5 rounded-[14px] border bg-surface-inset p-4",
        className,
      )}
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        className="shrink-0 text-muted-foreground"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v4M12 16h.01" />
      </svg>
      <span className="text-[12.5px] text-muted-foreground">{message}</span>
      {action ? <span className="ml-auto">{action}</span> : null}
    </div>
  );
}
