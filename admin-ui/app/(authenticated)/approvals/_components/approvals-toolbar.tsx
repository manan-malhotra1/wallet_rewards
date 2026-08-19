/**
 * Client toolbar for the unified Approvals page (1a design). Owns the four
 * facets — search, a status segmented control with counts, a type multi-select,
 * and a date-range preset — renders removable filter chips and the "X of Y"
 * line, then hands the filtered rows to the existing queue table.
 *
 * Since Story B7.1 the rows are a server-fetched WINDOW, not the full queue:
 * tab switches, status segment clicks, and the pager are real navigations
 * (each changes what the server fetches — `?tab=` / `?status=` / `?page=`),
 * while search, type, and date stay client-side over the fetched window. The
 * status segment counts come from the backend /counts endpoints (whole queue),
 * so they no longer reflect the other client facets.
 */
"use client";

import { GitPullRequest, Landmark, UserCog, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import type {
  ConfigChangeRequest,
  ConfigType,
  MoneyOperation,
  UserOperation,
} from "@/lib/api-types";
import {
  applyFilters,
  DEFAULT_FILTERS,
  STATUS_KEYS,
  type ApprovalFilters,
  type ApprovalRow,
  type DateRangeKey,
  type StatusKey,
} from "@/lib/approvals-filter";
import { DEFAULT_SERVER_STATUS, pageCount } from "@/lib/approvals-window";
import { configTypeLabel } from "@/lib/config-type-label";
import { moneyOperationLabel, moneyOperationSummary } from "@/lib/money-operation-label";
import { userOperationLabel, userOperationSummary } from "@/lib/user-operation-label";
import { cn } from "@/lib/utils";

import { ConfigRequestsTable } from "../../config-requests/_components/config-requests-table";
import { MoneyOperationsTable } from "../../money-operations/_components/money-operations-table";
import { UserOperationsTable } from "../../user-operations/_components/user-operations-table";
import {
  MultiSelectDropdown,
  SingleSelectDropdown,
  type FilterOption,
} from "./filter-dropdown";

export type TabKey = "configuration" | "transactions" | "users";

/** Tab metadata the server resolves by role, plus its per-queue count. */
export interface TabMeta {
  key: TabKey;
  label: string;
  count: number;
}

/** Icon per tab, reused for the tab bar and the empty state. */
const TAB_ICON: Record<TabKey, React.ComponentType<{ className?: string }>> = {
  configuration: GitPullRequest,
  transactions: Landmark,
  users: UserCog,
};

/** Human labels for the status segmented control (plus "All"). */
const STATUS_LABEL: Record<StatusKey | "ALL", string> = {
  PENDING: "Pending",
  CHANGES_REQUESTED: "Changes req.",
  APPLIED: "Applied",
  WITHDRAWN: "Withdrawn",
  ALL: "All",
};

/** Date-range presets, in trigger order. */
const DATE_OPTIONS: { value: DateRangeKey; label: string }[] = [
  { value: "all", label: "All time" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
];

const DATE_LABEL: Record<DateRangeKey, string> = {
  all: "All time",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "90d": "Last 90 days",
};

// ---- Type facet options per tab -----------------------------------------

const CONFIG_TYPES: ConfigType[] = [
  "pricing",
  "commission",
  "tax",
  "limit",
  "wallet_limit",
  "step_up",
];

const CONFIG_TYPE_OPTIONS: FilterOption[] = CONFIG_TYPES.map((value) => ({
  value,
  label: configTypeLabel(value),
}));

const MONEY_TYPE_OPTIONS: FilterOption[] = [
  "fund_user",
  "withdraw_user",
  "adjust_system_wallet",
  "create_bank_mirror",
].map((value) => ({ value, label: moneyOperationLabel(value) }));

const USER_TYPE_OPTIONS: FilterOption[] = [
  { value: "create_user", label: userOperationLabel("create_user") },
  { value: "update_user", label: userOperationLabel("update_user") },
];

/** The type-facet options offered for a given tab. */
function typeOptionsFor(tab: TabKey): FilterOption[] {
  if (tab === "configuration") return CONFIG_TYPE_OPTIONS;
  if (tab === "transactions") return MONEY_TYPE_OPTIONS;
  return USER_TYPE_OPTIONS;
}

// ---- Normalisers: typed queue rows → generic ApprovalRow -----------------

/** One-line entity text for a config request, used for display + search. */
function configSummary(req: ConfigChangeRequest): string {
  const p = req.payload ?? {};
  const extras = [p.transaction_type, p.user_type, p.currency]
    .filter((v) => typeof v === "string" && v)
    .join(" · ");
  const base = `${req.operation} ${configTypeLabel(req.config_type)}`;
  return extras ? `${base} · ${extras}` : base;
}

/** Reduce a config request to the generic row the toolbar filters on. */
function normalizeConfig(req: ConfigChangeRequest): ApprovalRow {
  return {
    id: req.id,
    status: req.status.toUpperCase(),
    type: req.config_type,
    createdAt: req.created_at,
    maker: req.maker_admin_name ?? req.maker_admin_id,
    makerId: req.maker_admin_id,
    summary: configSummary(req),
  };
}

function normalizeMoney(op: MoneyOperation): ApprovalRow {
  return {
    id: op.id,
    status: op.status.toUpperCase(),
    type: op.operation,
    createdAt: op.created_at,
    maker: op.maker_admin_name ?? op.maker_admin_id,
    makerId: op.maker_admin_id,
    summary: `${moneyOperationLabel(op.operation)} · ${moneyOperationSummary(op)}`,
  };
}

function normalizeUser(op: UserOperation): ApprovalRow {
  return {
    id: op.id,
    status: op.status.toUpperCase(),
    type: op.operation,
    createdAt: op.created_at,
    maker: op.maker_admin_name ?? op.maker_admin_id,
    makerId: op.maker_admin_id,
    summary: `${userOperationLabel(op.operation)} · ${userOperationSummary(op)}`,
  };
}

// ---- Initial-state parsing from the URL ----------------------------------

/**
 * Read the CLIENT facets (type, date, search) out of the current query string,
 * validated per tab. Status is a SERVER param since B7.1 (it changes what
 * window is fetched) and is parsed by the page, not here.
 */
function readFilters(
  params: URLSearchParams,
  validTypes: Set<string>,
): ApprovalFilters {
  const types = (params.get("type") ?? "")
    .split(",")
    .map((t) => t.trim())
    .filter((t) => validTypes.has(t));

  const dateParam = params.get("date");
  const dateRange: DateRangeKey =
    dateParam === "7d" || dateParam === "30d" || dateParam === "90d" || dateParam === "all"
      ? dateParam
      : DEFAULT_FILTERS.dateRange;

  return { types, dateRange, q: params.get("q") ?? "" };
}

// ---- The toolbar ---------------------------------------------------------

export interface ApprovalsToolbarProps {
  tabs: TabMeta[];
  activeTab: TabKey;
  tenantId: string;
  currentAdminId: string;
  canApprove: boolean;
  serviceNames: Record<string, string>;
  configRequests: ConfigChangeRequest[];
  moneyOperations: MoneyOperation[];
  userOperations: UserOperation[];
  /** The server-applied status filter the fetched window reflects. */
  serverStatus: StatusKey | "ALL";
  /** Whole-queue per-status counts (from /counts), for the status segments. */
  statusCounts: Record<StatusKey | "ALL", number>;
  /** Rows matching `serverStatus` across the WHOLE queue (drives the pager). */
  queueTotal: number;
  /** Current 1-based page of the server window. */
  page: number;
  /** Server window size (rows per page). */
  pageSize: number;
}

export function ApprovalsToolbar(props: ApprovalsToolbarProps) {
  const { activeTab, tabs, serverStatus, statusCounts, queueTotal, page, pageSize } = props;
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();

  const typeOptions = typeOptionsFor(activeTab);
  const validTypes = React.useMemo(
    () => new Set(typeOptions.map((o) => o.value)),
    [typeOptions],
  );

  // Facets are client state; the URL is a mirror for shareability. Seed once
  // from the query string (a shared link reproduces the exact view).
  const [filters, setFilters] = React.useState<ApprovalFilters>(() =>
    readFilters(new URLSearchParams(searchParams.toString()), validTypes),
  );

  // Normalise the active tab's typed rows into the generic filter shape. Only
  // the active tab carries data; the others are empty arrays.
  const normalized = React.useMemo<ApprovalRow[]>(() => {
    if (activeTab === "configuration") return props.configRequests.map(normalizeConfig);
    if (activeTab === "transactions") return props.moneyOperations.map(normalizeMoney);
    return props.userOperations.map(normalizeUser);
  }, [activeTab, props.configRequests, props.moneyOperations, props.userOperations]);

  // Client facets over the fetched window (the window is already
  // status-filtered server-side; the segment counts come from /counts).
  const filtered = React.useMemo(
    () => applyFilters(normalized, filters),
    [normalized, filters],
  );
  const shown = filtered.length;
  const total = normalized.length;

  // Build the query string for a given server window (status + page) with the
  // current client facets carried along, so a status/page navigation — which
  // re-runs the server component and remounts this toolbar — preserves them.
  const buildQuery = React.useCallback(
    (next: ApprovalFilters, status: StatusKey | "ALL", targetPage: number) => {
      const sp = new URLSearchParams();
      sp.set("tab", activeTab);
      if (status !== DEFAULT_SERVER_STATUS) sp.set("status", status);
      if (targetPage > 1) sp.set("page", String(targetPage));
      if (next.types.length > 0) sp.set("type", next.types.join(","));
      if (next.dateRange !== DEFAULT_FILTERS.dateRange) sp.set("date", next.dateRange);
      if (next.q.trim()) sp.set("q", next.q.trim());
      return `${pathname}?${sp.toString()}`;
    },
    [activeTab, pathname],
  );

  // A status or page change is a REAL navigation — the server fetches a new
  // window. A status change resets to page 1 (fresh window).
  const navigateToWindow = React.useCallback(
    (status: StatusKey | "ALL", targetPage: number) => {
      router.push(buildQuery(filters, status, targetPage));
    },
    [buildQuery, filters, router],
  );

  // Mirror the CLIENT facets into the address bar without re-running the
  // server component (History API, not router navigation) — search stays
  // snappy and no stale refetch flashes. Only non-default facets are written.
  const syncUrl = React.useCallback(
    (next: ApprovalFilters) => {
      window.history.replaceState(null, "", buildQuery(next, serverStatus, page));
    },
    [buildQuery, page, serverStatus],
  );

  /** Apply a partial facet change: update state and mirror to the URL. */
  const update = React.useCallback(
    (partial: Partial<ApprovalFilters>) => {
      setFilters((prev) => {
        const next = { ...prev, ...partial };
        syncUrl(next);
        return next;
      });
    },
    [syncUrl],
  );

  // Full reset — client facets AND server window. The navigation re-renders
  // the server component but PRESERVES this client component instance, so the
  // facet state must be reset explicitly, not just erased from the URL.
  const resetAll = React.useCallback(() => {
    setFilters({ ...DEFAULT_FILTERS });
    router.push(`${pathname}?tab=${activeTab}`);
  }, [activeTab, pathname, router]);

  // Which chips are active (a facet away from its default)? Status is the
  // server-applied filter; the rest are client facets.
  const statusChipActive = serverStatus !== DEFAULT_SERVER_STATUS;
  const dateChipActive = filters.dateRange !== DEFAULT_FILTERS.dateRange;
  const anyChip = statusChipActive || dateChipActive || filters.types.length > 0;

  const pages = pageCount(queueTotal, pageSize);

  const TabEmptyIcon = TAB_ICON[activeTab];

  return (
    <div className="space-y-4">
      {/* Tab bar — one queue per tab, each with its pending-queue count. */}
      <div className="border-b border-border pb-3">
        <nav className="flex flex-wrap gap-1" aria-label="Approval queues">
          {tabs.map((t) => {
            const Icon = TAB_ICON[t.key];
            const active = t.key === activeTab;
            return (
              <Link
                key={t.key}
                href={`/approvals?tab=${t.key}`}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-primary font-medium text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )}
              >
                <Icon className="size-4" />
                {t.label}
                <span
                  className={cn(
                    "rounded-full px-1.5 text-xs tabular-nums",
                    active ? "bg-primary-foreground/20" : "bg-muted",
                  )}
                >
                  {t.count}
                </span>
              </Link>
            );
          })}
        </nav>
      </div>

      {/* One toolbar: search · status segments · type · date · save-as-view. */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-[240px] flex-1">
          <Input
            type="search"
            aria-label="Search approvals"
            placeholder="Search by maker, entity or request ID"
            value={filters.q}
            onChange={(e) => update({ q: e.target.value })}
          />
        </div>

        <StatusSegments
          counts={statusCounts}
          value={serverStatus}
          onChange={(status) => navigateToWindow(status, 1)}
        />

        <MultiSelectDropdown
          label="Type"
          options={typeOptions}
          selected={filters.types}
          onChange={(types) => update({ types })}
        />

        <SingleSelectDropdown
          options={DATE_OPTIONS}
          value={filters.dateRange}
          onChange={(v) => update({ dateRange: v as DateRangeKey })}
        />

        <Tooltip content="Saved views are coming soon">
          {/* Placeholder — saved-view persistence is out of scope. */}
          <span>
            <Button variant="outline" size="md" disabled aria-disabled="true">
              + Save as view
            </Button>
          </span>
        </Tooltip>
      </div>

      {/* Applied-filter chips — one per active non-default facet. */}
      {anyChip && (
        <div className="flex flex-wrap items-center gap-2">
          {statusChipActive && (
            <FilterChip
              label={`Status: ${STATUS_LABEL[serverStatus]}`}
              onRemove={() => navigateToWindow(DEFAULT_SERVER_STATUS, 1)}
            />
          )}
          {filters.types.map((t) => (
            <FilterChip
              key={t}
              label={typeOptions.find((o) => o.value === t)?.label ?? t}
              onRemove={() => update({ types: filters.types.filter((x) => x !== t) })}
            />
          ))}
          {dateChipActive && (
            <FilterChip
              label={DATE_LABEL[filters.dateRange]}
              onRemove={() => update({ dateRange: DEFAULT_FILTERS.dateRange })}
            />
          )}
          <Button variant="ghost" size="xs" onClick={resetAll}>
            Clear all
          </Button>
        </div>
      )}

      {/* "X of Y" count line + the server-window pager (only when the queue
          exceeds one fetched page for the current status). */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground tabular-nums">
          {shown} of {total} {total === 1 ? "request" : "requests"}
          {pages > 1 && ` on this page · ${queueTotal} in queue`}
        </p>
        {pages > 1 && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="xs"
              disabled={page <= 1}
              onClick={() => navigateToWindow(serverStatus, page - 1)}
            >
              Previous
            </Button>
            <span className="text-xs text-muted-foreground tabular-nums">
              Page {page} of {pages}
            </span>
            <Button
              variant="outline"
              size="xs"
              disabled={page >= pages}
              onClick={() => navigateToWindow(serverStatus, page + 1)}
            >
              Next
            </Button>
          </div>
        )}
      </div>

      {/* The active queue's table, fed the filtered rows. Three empty states:
          the queue itself is empty; the server status window is empty (the
          default PENDING window shows no chip, so name the status instead of
          blaming "filters"); or the client facets emptied a non-empty page. */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={TabEmptyIcon}
          title={
            statusCounts.ALL === 0
              ? "No requests in this queue"
              : total === 0
                ? `No ${STATUS_LABEL[serverStatus].toLowerCase()} requests`
                : "No matching requests"
          }
          description={
            statusCounts.ALL === 0
              ? "Proposed changes appear here for an approver to review and approve."
              : total === 0
                ? "Nothing in this queue has that status. Pick another status segment to see the rest."
                : "No rows on this page match the current filters — search, type, and date apply only to the fetched page, not the whole queue. Adjust or clear them, or page through the queue."
          }
        />
      ) : (
        <ActiveTable {...props} filteredIds={new Set(filtered.map((r) => r.id))} />
      )}
    </div>
  );
}

/** The status segmented control — one button per status, each with a count. */
function StatusSegments({
  counts,
  value,
  onChange,
}: {
  counts: Record<StatusKey | "ALL", number>;
  value: StatusKey | "ALL";
  onChange: (status: StatusKey | "ALL") => void;
}) {
  const segments: (StatusKey | "ALL")[] = [...STATUS_KEYS, "ALL"];
  return (
    <div
      className="inline-flex items-center rounded-md border border-input bg-background p-0.5"
      role="group"
      aria-label="Filter by status"
    >
      {segments.map((seg) => {
        const active = seg === value;
        return (
          <button
            key={seg}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(seg)}
            className={cn(
              "rounded-sm px-2.5 py-1 text-xs font-medium transition-colors",
              active
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {STATUS_LABEL[seg]}
            <span className="ml-1 tabular-nums opacity-70">{counts[seg]}</span>
          </button>
        );
      })}
    </div>
  );
}

/** A removable applied-filter chip. */
function FilterChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <Badge variant="secondary" className="gap-1 pr-1">
      {label}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${label}`}
        className="rounded-sm p-0.5 hover:bg-background/60"
      >
        <X className="size-3" aria-hidden="true" />
      </button>
    </Badge>
  );
}

/**
 * Render the active tab's existing queue table, restricted to the rows that
 * survived filtering (matched by id). Reuses the per-domain tables + drawers
 * unchanged.
 */
function ActiveTable({
  activeTab,
  tenantId,
  currentAdminId,
  canApprove,
  serviceNames,
  configRequests,
  moneyOperations,
  userOperations,
  filteredIds,
}: ApprovalsToolbarProps & { filteredIds: Set<string> }) {
  if (activeTab === "configuration") {
    return (
      <ConfigRequestsTable
        requests={configRequests.filter((r) => filteredIds.has(r.id))}
        tenantId={tenantId}
        canApprove={canApprove}
        currentAdminId={currentAdminId}
        serviceNames={serviceNames}
      />
    );
  }
  if (activeTab === "transactions") {
    return (
      <MoneyOperationsTable
        operations={moneyOperations.filter((o) => filteredIds.has(o.id))}
        tenantId={tenantId}
        canApprove={canApprove}
        currentAdminId={currentAdminId}
      />
    );
  }
  return (
    <UserOperationsTable
      operations={userOperations.filter((o) => filteredIds.has(o.id))}
      tenantId={tenantId}
      canApprove={canApprove}
      currentAdminId={currentAdminId}
    />
  );
}
