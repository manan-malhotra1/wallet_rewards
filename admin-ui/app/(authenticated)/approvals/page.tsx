/**
 * Unified approvals page (Unified-approvals initiative). One screen with a
 * role-gated tab bar over the three maker-checker queues:
 *   - Configuration  → config_requests   (role: config-approver)
 *   - Transactions   → money_operations  (role: treasury-approver)
 *   - Users          → user_operations   (role: user-approver)
 *
 * A platform-admin sees every tab; other admins see only the tabs matching an
 * approver role they hold. The active tab defaults to the first one they can
 * see; if they can see none, an empty state is shown.
 *
 * A single status filter (Pending / Changes requested / Applied / Withdrawn /
 * All) applies to the active tab. The Configuration tab additionally carries a
 * config-type sub-filter. All three selections live in the URL
 * (?tab=&status=&config_type=) so a view is shareable. The per-domain queue
 * tables + detail drawers are reused unchanged from the original routes (now
 * thin redirects here).
 */
import Link from "next/link";
import { GitPullRequest, Landmark, UserCog } from "lucide-react";

import { auth } from "@/auth";
import { ApiError } from "@/lib/api";
import {
  listConfigRequests,
  listMoneyOperations,
  listServices,
  listUserOperations,
} from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import type {
  ConfigChangeRequest,
  ConfigRequestStatus,
  ConfigType,
  MoneyOperation,
  Service,
  UserOperation,
} from "@/lib/api-types";
import { configTypeLabel } from "@/lib/config-type-label";
import { cn } from "@/lib/utils";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { ConfigRequestsTable } from "../config-requests/_components/config-requests-table";
import { MoneyOperationsTable } from "../money-operations/_components/money-operations-table";
import { UserOperationsTable } from "../user-operations/_components/user-operations-table";

export const dynamic = "force-dynamic";

type TabKey = "configuration" | "transactions" | "users";

/** A queue tab, the approver role that unlocks it, and its empty-state icon. */
const TABS: {
  key: TabKey;
  label: string;
  role: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  {
    key: "configuration",
    label: "Configuration",
    role: "config-approver",
    icon: GitPullRequest,
  },
  {
    key: "transactions",
    label: "Transactions",
    role: "treasury-approver",
    icon: Landmark,
  },
  { key: "users", label: "Users", role: "user-approver", icon: UserCog },
];

/**
 * Shared status filter, applied to the active tab's query. `undefined` = all.
 * The three domains share an identical status vocabulary, so one filter drives
 * every tab.
 */
const STATUS_FILTERS: {
  key: string;
  label: string;
  status?: ConfigRequestStatus;
}[] = [
  { key: "pending", label: "Pending", status: "PENDING" },
  { key: "changes", label: "Changes requested", status: "CHANGES_REQUESTED" },
  { key: "applied", label: "Applied", status: "APPLIED" },
  { key: "withdrawn", label: "Withdrawn", status: "WITHDRAWN" },
  { key: "all", label: "All", status: undefined },
];

/** Config-type sub-filter (Configuration tab only). `undefined` = all types. */
const CONFIG_TYPE_FILTERS: { key: string; type?: ConfigType }[] = [
  { key: "all", type: undefined },
  { key: "pricing", type: "pricing" },
  { key: "commission", type: "commission" },
  { key: "tax", type: "tax" },
  { key: "limit", type: "limit" },
  { key: "wallet_limit", type: "wallet_limit" },
  { key: "step_up", type: "step_up" },
];

/** Build a shareable /approvals href from the given (defined) query params. */
function approvalsHref(params: {
  tab?: string;
  status?: string;
  config_type?: string;
}): string {
  const sp = new URLSearchParams();
  if (params.tab) sp.set("tab", params.tab);
  if (params.status) sp.set("status", params.status);
  if (params.config_type) sp.set("config_type", params.config_type);
  const qs = sp.toString();
  return qs ? `/approvals?${qs}` : "/approvals";
}

/** A pill-style nav row shared by the tab bar and the filter rows. */
function NavPills({
  items,
}: {
  items: { key: string; label: string; href: string; active: boolean }[];
}) {
  return (
    <nav className="flex flex-wrap gap-1">
      {items.map((it) => (
        <Link
          key={it.key}
          href={it.href}
          className={cn(
            "rounded-md px-3 py-1.5 text-sm transition-colors",
            it.active
              ? "bg-primary text-primary-foreground font-medium"
              : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
          )}
        >
          {it.label}
        </Link>
      ))}
    </nav>
  );
}

export default async function ApprovalsPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; status?: string; config_type?: string }>;
}) {
  const { tab, status, config_type } = await searchParams;

  const session = await auth();
  const roles = session?.user?.roles ?? [];
  const isPlatformAdmin = roles.includes("platform-admin");
  const currentAdminId = session?.user?.id ?? "";
  // A platform-admin sees every queue; everyone else sees only queues matching
  // an approver role they hold. Approve/withdraw affordances inside each queue
  // stay gated on the specific approver role (the backend re-validates).
  const canSee = (role: string) => isPlatformAdmin || roles.includes(role);
  const visibleTabs = TABS.filter((t) => canSee(t.role));

  const activeStatus =
    STATUS_FILTERS.find((s) => s.key === status) ?? STATUS_FILTERS[0];
  const activeConfigType =
    CONFIG_TYPE_FILTERS.find((c) => c.key === config_type) ??
    CONFIG_TYPE_FILTERS[0];

  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={GitPullRequest}
          title="No active tenant"
          description="Switch to a tenant to review its approval queues."
        />
      </div>
    );
  }

  if (visibleTabs.length === 0) {
    return (
      <div>
        <PageHeader
          title="Approvals"
          subtitle="Review and approve proposed configuration, treasury, and user changes (maker-checker)."
        />
        <div className="p-6">
          <EmptyState
            icon={GitPullRequest}
            title="No approval queues"
            description="You don't hold any approver role. Ask an administrator for the config-approver, treasury-approver, or user-approver role to review requests here."
          />
        </div>
      </div>
    );
  }

  const activeTab = visibleTabs.find((t) => t.key === tab) ?? visibleTabs[0];

  // Fetch only the active tab's data — one queue is on screen at a time.
  let error: ApiError | null = null;
  let configRequests: ConfigChangeRequest[] = [];
  let serviceNames: Record<string, string> = {};
  let moneyOperations: MoneyOperation[] = [];
  let userOperations: UserOperation[] = [];
  try {
    if (activeTab.key === "configuration") {
      let services: Service[] = [];
      [configRequests, services] = await Promise.all([
        listConfigRequests(activeTenantId, activeStatus.status, activeConfigType.type),
        listServices(activeTenantId, "active"),
      ]);
      serviceNames = Object.fromEntries(
        services.map((s) => [s.code, s.display_name]),
      );
    } else if (activeTab.key === "transactions") {
      moneyOperations = await listMoneyOperations(activeTenantId, activeStatus.status);
    } else {
      userOperations = await listUserOperations(activeTenantId, activeStatus.status);
    }
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  const tabPills = visibleTabs.map((t) => ({
    key: t.key,
    label: t.label,
    // Preserve the status across tabs (shared filter); config_type is
    // config-only, so it resets when switching tabs.
    href: approvalsHref({ tab: t.key, status: activeStatus.key }),
    active: t.key === activeTab.key,
  }));

  const statusPills = STATUS_FILTERS.map((s) => ({
    key: s.key,
    label: s.label,
    href: approvalsHref({
      tab: activeTab.key,
      status: s.key,
      config_type:
        activeTab.key === "configuration" ? activeConfigType.key : undefined,
    }),
    active: s.key === activeStatus.key,
  }));

  const configTypePills = CONFIG_TYPE_FILTERS.map((c) => ({
    key: c.key,
    label: c.type ? configTypeLabel(c.type) : "All",
    href: approvalsHref({
      tab: "configuration",
      status: activeStatus.key,
      config_type: c.key,
    }),
    active: c.key === activeConfigType.key,
  }));

  return (
    <div>
      <PageHeader
        title="Approvals"
        subtitle="Review and approve proposed configuration, treasury, and user changes (maker-checker)."
      />
      <div className="space-y-4 p-6">
        {/* Tab bar — one queue per tab, gated by approver role. */}
        <div className="border-b border-border pb-3">
          <NavPills items={tabPills} />
        </div>

        {/* Shared status filter across the whole page. */}
        <NavPills items={statusPills} />

        {/* Config-type sub-filter lives inside the Configuration tab only. */}
        {activeTab.key === "configuration" && <NavPills items={configTypePills} />}

        {error && (
          <ErrorBanner
            title="Couldn't load approvals"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}

        {!error && activeTab.key === "configuration" && (
          configRequests.length === 0 ? (
            <EmptyState
              icon={GitPullRequest}
              title="No requests in this view"
              description="Proposed config changes appear here for a config-approver to review and approve."
            />
          ) : (
            <ConfigRequestsTable
              requests={configRequests}
              tenantId={activeTenantId}
              canApprove={roles.includes("config-approver")}
              currentAdminId={currentAdminId}
              serviceNames={serviceNames}
            />
          )
        )}

        {!error && activeTab.key === "transactions" && (
          moneyOperations.length === 0 ? (
            <EmptyState
              icon={Landmark}
              title="No operations in this view"
              description="Proposed treasury moves appear here for a treasury-approver to review and approve."
            />
          ) : (
            <MoneyOperationsTable
              operations={moneyOperations}
              tenantId={activeTenantId}
              canApprove={roles.includes("treasury-approver")}
              currentAdminId={currentAdminId}
            />
          )
        )}

        {!error && activeTab.key === "users" && (
          userOperations.length === 0 ? (
            <EmptyState
              icon={UserCog}
              title="No operations in this view"
              description="Proposed user create / edit requests appear here for a user-approver to review and approve."
            />
          ) : (
            <UserOperationsTable
              operations={userOperations}
              tenantId={activeTenantId}
              canApprove={roles.includes("user-approver")}
              currentAdminId={currentAdminId}
            />
          )
        )}
      </div>
    </div>
  );
}
