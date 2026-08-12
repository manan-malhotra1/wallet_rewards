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
 * This server component resolves the visible tabs, fetches each visible queue's
 * FULL dataset (all statuses — the counts on the tab bar need every row), and
 * hands the active tab's rows + per-tab counts + role flags into the client
 * `<ApprovalsToolbar>`, which owns the search / status / type / date facets and
 * renders the per-domain queue tables + detail drawers (reused unchanged).
 */
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
  MoneyOperation,
  Service,
  UserOperation,
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

export default async function ApprovalsPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string }>;
}) {
  const { tab } = await searchParams;

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

  const activeTab: TabKey =
    visibleTabs.find((t) => t.key === tab)?.key ?? visibleTabs[0].key;

  // Fetch the FULL dataset (all statuses) for every visible queue: the tab-bar
  // counts need every row, and the toolbar filters client-side. Admin volumes
  // are small, so three list calls on load is acceptable. Only visible queues
  // are fetched — a queue the admin can't see is never requested (no 403 risk).
  let error: ApiError | null = null;
  let configRequests: ConfigChangeRequest[] = [];
  let moneyOperations: MoneyOperation[] = [];
  let userOperations: UserOperation[] = [];
  let serviceNames: Record<string, string> = {};
  try {
    const jobs: Promise<void>[] = [];
    if (canSee("config-approver")) {
      jobs.push(
        Promise.all([
          listConfigRequests(activeTenantId, undefined, undefined),
          listServices(activeTenantId, "active"),
        ]).then(([requests, services]) => {
          configRequests = requests;
          serviceNames = Object.fromEntries(
            services.map((s: Service) => [s.code, s.display_name]),
          );
        }),
      );
    }
    if (canSee("treasury-approver")) {
      jobs.push(
        listMoneyOperations(activeTenantId, undefined).then((ops) => {
          moneyOperations = ops;
        }),
      );
    }
    if (canSee("user-approver")) {
      jobs.push(
        listUserOperations(activeTenantId, undefined).then((ops) => {
          userOperations = ops;
        }),
      );
    }
    await Promise.all(jobs);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  const countFor = (key: TabKey): number => {
    if (key === "configuration") return configRequests.length;
    if (key === "transactions") return moneyOperations.length;
    return userOperations.length;
  };
  const tabs: TabMeta[] = visibleTabs.map((t) => ({
    key: t.key,
    label: t.label,
    count: countFor(t.key),
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
            configRequests={configRequests}
            moneyOperations={moneyOperations}
            userOperations={userOperations}
          />
        )}
      </div>
    </div>
  );
}
