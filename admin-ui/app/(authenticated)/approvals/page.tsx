/**
 * Unified approvals page (Unified-approvals initiative). One screen with a
 * role-gated tab bar over the three maker-checker queues:
 *   - Configuration  → config_requests   (role: config-approver)
 *   - Transactions   → money_operations  (role: treasury-approver)
 *   - Users          → user_operations   (role: user-approver)
 *
 * A platform-admin sees every tab; other admins see only the tabs matching an
 * approver role they hold. Without an explicit ?tab= the active tab defaults
 * to the first visible queue with PENDING items (falling back to the first
 * visible tab); if they can see none, an empty state is shown.
 *
 * Fetch strategy (Stories B7.1/B7.2 — this page must scale past thousands of
 * rows): every visible queue contributes only a cheap /counts call (tab-bar
 * totals + default-tab resolution); actual rows are fetched for the ACTIVE tab
 * only, as one status-filtered window (`?status=`, default PENDING; `?page=` ×
 * APPROVALS_PAGE_SIZE). The search (`?q=`) is server-side and covers the WHOLE
 * queue — while searching, one extra q-scoped /counts call keeps the segments
 * and pager truthful. The client `<ApprovalsToolbar>` keeps only the type /
 * date facets client-side over that window and renders the per-domain queue
 * tables + detail drawers (reused unchanged).
 */
import { auth } from "@/auth";
import { ApiError } from "@/lib/api";
import {
  getConfigRequestCounts,
  getMoneyOperationCounts,
  getUserOperationCounts,
  getUserTypeCatalog,
  listConfigRequests,
  listMoneyOperations,
  listServices,
  listUserOperations,
} from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import { resolveActiveTab } from "@/lib/approvals-filter";
import {
  APPROVALS_PAGE_SIZE,
  pageCount,
  readPage,
  readServerQ,
  readServerStatus,
  serverStatusParam,
  statusCountsWithAll,
  windowOffset,
} from "@/lib/approvals-window";
import type {
  ConfigChangeRequest,
  MoneyOperation,
  QueueCounts,
  Service,
  UserOperation,
  UserTypeCatalog,
} from "@/lib/api-types";

import { GitPullRequest } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import {
  ApprovalsToolbar,
  type TabKey,
  type TabMeta,
} from "./_components/approvals-toolbar";

export const dynamic = "force-dynamic";

/** A queue tab and the approver role that unlocks it. */
const TABS: { key: TabKey; label: string; role: string }[] = [
  { key: "configuration", label: "Configuration", role: "config-approver" },
  { key: "transactions", label: "Transactions", role: "treasury-approver" },
  { key: "users", label: "Users", role: "user-approver" },
];

/** The counts endpoint for a queue tab; `q` scopes counts to search matches. */
function countsFor(key: TabKey, tenantId: string, q?: string): Promise<QueueCounts> {
  if (key === "configuration") return getConfigRequestCounts(tenantId, q);
  if (key === "transactions") return getMoneyOperationCounts(tenantId, q);
  return getUserOperationCounts(tenantId, q);
}

export default async function ApprovalsPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; status?: string; page?: string; q?: string }>;
}) {
  const { tab, status: statusParam, page: pageParam, q: qParam } = await searchParams;

  const session = await auth();
  const roles = session?.user?.roles ?? [];
  const isPlatformAdmin = roles.includes("platform-admin");
  const currentAdminId = session?.user?.id ?? "";
  // A platform-admin sees every queue; everyone else sees only queues matching
  // an approver role they hold. Approve/withdraw affordances inside each queue
  // stay gated on the specific approver role (the backend re-validates).
  const canSee = (role: string) => isPlatformAdmin || roles.includes(role);
  const visibleTabs = TABS.filter((t) => canSee(t.role));

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

  const serverStatus = readServerStatus(statusParam);
  const serverQ = readServerQ(qParam);
  let page = readPage(pageParam);
  // Rows the current server status filter matches ACROSS the whole queue —
  // drives the pager ("page P of N"), not just the fetched window.
  let queueTotal = 0;

  let error: ApiError | null = null;
  let configRequests: ConfigChangeRequest[] = [];
  let moneyOperations: MoneyOperation[] = [];
  let userOperations: UserOperation[] = [];
  let serviceNames: Record<string, string> = {};
  // The Users queue renders proposed user types; types are runtime data, so the
  // labels come from the catalog. Null degrades to showing the raw code.
  let userTypeCatalog: UserTypeCatalog | null = null;
  const counts: Partial<Record<TabKey, QueueCounts>> = {};
  let activeTab: TabKey = visibleTabs[0].key;
  // The counts driving the active tab's segments and pager. Equal to the
  // tab's plain counts unless a search is active, in which case they cover
  // only the matching rows (one extra grouped query).
  let activeCounts: QueueCounts = { total: 0, by_status: {} };

  try {
    // One cheap grouped-count query per visible queue — no rows fetched.
    // Always unfiltered: tab badges and default-tab resolution describe the
    // whole queue, whatever the search box holds.
    await Promise.all(
      visibleTabs.map(async (t) => {
        counts[t.key] = await countsFor(t.key, activeTenantId);
      }),
    );

    // Land the checker where the work is: without an explicit ?tab=, default
    // to the first visible queue with PENDING items, not a fixed first tab.
    const pendingOf = (key: TabKey) => counts[key]?.by_status["PENDING"] ?? 0;
    activeTab =
      resolveActiveTab(
        visibleTabs.map((t) => ({ key: t.key, pending: pendingOf(t.key) })),
        tab,
      ) ?? visibleTabs[0].key;

    activeCounts = serverQ
      ? await countsFor(activeTab, activeTenantId, serverQ)
      : (counts[activeTab] ?? { total: 0, by_status: {} });

    queueTotal =
      serverStatus === "ALL"
        ? activeCounts.total
        : (activeCounts.by_status[serverStatus] ?? 0);
    // Clamp a stale bookmark or hand-edited ?page= to the real page count, so
    // a shrunken queue never strands the user on an empty out-of-range window.
    page = Math.min(page, pageCount(queueTotal, APPROVALS_PAGE_SIZE));

    // Rows for the ACTIVE tab only, as one status-filtered (and, when
    // searching, whole-queue q-filtered) window.
    const statusFilter = serverStatusParam(serverStatus);
    const q = serverQ || undefined;
    const offset = windowOffset(page, APPROVALS_PAGE_SIZE);
    if (activeTab === "configuration") {
      const [requests, services] = await Promise.all([
        listConfigRequests(
          activeTenantId,
          statusFilter,
          undefined,
          APPROVALS_PAGE_SIZE,
          offset,
          q,
        ),
        listServices(activeTenantId, "active"),
      ]);
      configRequests = requests;
      serviceNames = Object.fromEntries(
        services.map((s: Service) => [s.code, s.display_name]),
      );
    } else if (activeTab === "transactions") {
      moneyOperations = await listMoneyOperations(
        activeTenantId,
        statusFilter,
        APPROVALS_PAGE_SIZE,
        offset,
        q,
      );
    } else {
      userTypeCatalog = await getUserTypeCatalog(activeTenantId);
      userOperations = await listUserOperations(
        activeTenantId,
        statusFilter,
        APPROVALS_PAGE_SIZE,
        offset,
        q,
      );
    }
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  const tabs: TabMeta[] = visibleTabs.map((t) => ({
    key: t.key,
    label: t.label,
    count: counts[t.key]?.total ?? 0,
  }));

  // The approve/withdraw affordance for the ACTIVE queue's table.
  const canApproveActive =
    activeTab === "configuration"
      ? roles.includes("config-approver")
      : activeTab === "transactions"
        ? roles.includes("treasury-approver")
        : roles.includes("user-approver");

  return (
    <div>
      <PageHeader
        title="Approvals"
        subtitle="Review and approve proposed configuration, treasury, and user changes (maker-checker)."
      />
      <div className="space-y-4 p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load approvals"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && (
          <ApprovalsToolbar
            tabs={tabs}
            activeTab={activeTab}
            tenantId={activeTenantId}
            currentAdminId={currentAdminId}
            canApprove={canApproveActive}
            serviceNames={serviceNames}
            userTypeCatalog={userTypeCatalog}
            configRequests={configRequests}
            moneyOperations={moneyOperations}
            userOperations={userOperations}
            serverStatus={serverStatus}
            serverQ={serverQ}
            statusCounts={statusCountsWithAll(activeCounts)}
            queueTotal={queueTotal}
            page={page}
            pageSize={APPROVALS_PAGE_SIZE}
          />
        )}
      </div>
    </div>
  );
}
