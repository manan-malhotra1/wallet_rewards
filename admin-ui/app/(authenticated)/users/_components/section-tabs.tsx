/**
 * <SectionTabs> — one row of collapsed section headers; the selected one
 * expands full-width underneath.
 *
 * Replaces a stack of full-width accordions on the user-detail page. Five
 * stacked panels made the page scroll far longer than its content warranted,
 * and pairing them two-up just squeezed the wide ones. A single header row
 * costs one line of height no matter how many sections exist, and whatever is
 * open gets the full page width — which the transactions table and the
 * balances grid both need.
 *
 * Starts fully collapsed; clicking the open tab closes it again, so "nothing
 * expanded" stays reachable. Content is rendered by the server component that
 * owns the data and passed in as elements, so this stays a thin shell.
 */
"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface SectionTab {
  /** Stable key + the value tracked in state. */
  id: string;
  label: string;
  /** Short hint shown under the label while the tab is open. */
  description?: string;
  content: React.ReactNode;
}

export function SectionTabs({
  tabs,
  defaultOpenId = null,
}: {
  tabs: SectionTab[];
  /** Tab to expand on first paint; null (default) starts fully collapsed. */
  defaultOpenId?: string | null;
}) {
  const [openId, setOpenId] = React.useState<string | null>(defaultOpenId);
  const open = tabs.find((t) => t.id === openId) ?? null;

  return (
    <div className="space-y-4">
      <div
        role="tablist"
        aria-label="User detail sections"
        className="glass-panel flex flex-wrap items-center gap-1.5 rounded-lg p-1.5"
      >
        {tabs.map((tab) => {
          const active = tab.id === openId;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls={`section-panel-${tab.id}`}
              // Clicking the open tab collapses it — "all closed" is a state
              // the operator can get back to.
              onClick={() => setOpenId(active ? null : tab.id)}
              className={cn(
                "rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
              )}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {open ? (
        <section
          id={`section-panel-${open.id}`}
          role="tabpanel"
          className="glass-panel rounded-lg px-5 py-4"
        >
          {open.description ? (
            <p className="mb-3 text-xs text-muted-foreground">{open.description}</p>
          ) : null}
          {open.content}
        </section>
      ) : null}
    </div>
  );
}
