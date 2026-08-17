"use client";

/**
 * Resolves what a panel should render: its chart, an empty placeholder, or an
 * inline "couldn't load" notice.
 *
 * `loadDashboardData` settles every dataset independently and returns `null`
 * for the ones that failed, so a single flaky endpoint degrades to one notice
 * instead of blanking the page. Centralising the three-way choice here is what
 * keeps eight panels from each inventing their own version of "no data".
 */
import * as React from "react";

import { EmptyPlot, PanelNotice } from "./panel";

/** Which of the three states a panel is in. */
export type PanelStatus = "ready" | "empty" | "error";

/**
 * Classify a panel's dataset.
 *
 * @param data - the dataset, or null when its fetch was rejected
 * @param isEmpty - whether a successfully fetched dataset has nothing to plot
 */
export function panelStatus(data: unknown, isEmpty: boolean): PanelStatus {
  if (data === null || data === undefined) return "error";
  return isEmpty ? "empty" : "ready";
}

/** A chart glyph for ranges with no activity. */
export const TrendGlyph = (
  <svg
    width="22"
    height="22"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M3 17l5-6 4 3 5-8" />
    <path d="M3 21h18" />
  </svg>
);

/** A bar glyph for money panels with no movement. */
export const BarsGlyph = (
  <svg
    width="22"
    height="22"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M4 18h4V9H4zM10 18h4V5h-4zM16 18h4v-6h-4z" />
  </svg>
);

interface Props {
  status: PanelStatus;
  /** Copy for the empty state — phrased for this panel, not generic. */
  emptyMessage: string;
  emptyIcon?: React.ReactNode;
  /** Height utility for the placeholder, matched to the chart it stands in for. */
  emptyClassName?: string;
  /** Refetches the whole dashboard for the current range. */
  onRetry: () => void;
  children: React.ReactNode;
}

export function PanelState({
  status,
  emptyMessage,
  emptyIcon = TrendGlyph,
  emptyClassName = "mt-3.5 h-[190px]",
  onRetry,
  children,
}: Props) {
  if (status === "error") {
    return (
      <PanelNotice
        className="mt-3.5"
        message="Couldn't load this panel. The other metrics are up to date."
        action={
          <button
            type="button"
            onClick={onRetry}
            className="rounded-[9px] border px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-primary-line focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            Retry
          </button>
        }
      />
    );
  }
  if (status === "empty") {
    return <EmptyPlot message={emptyMessage} icon={emptyIcon} className={emptyClassName} />;
  }
  return <>{children}</>;
}
