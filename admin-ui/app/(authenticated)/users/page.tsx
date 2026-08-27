/**
 * Users page — identifier lookup → full user detail.
 *
 * On submit the page server-side resolves the identifier to a `user_id`,
 * then fetches the full user-detail payload (identifiers, profile,
 * accounts with balances) and renders the detail card.
 */
import { UserPlus, Users } from "lucide-react";

import { auth } from "@/auth";
import { getActiveTenantId } from "@/lib/active-tenant";
import {
  getUserDetail,
  getUserTypeCatalog,
  listUserOperations,
  listUserReports,
  listUserTransactions,
  resolveIdentifier,
  type UserTransaction,
} from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";
import type { UserReport } from "@/lib/api-endpoints";
import type { UserOperation, UserTypeCatalog } from "@/lib/api-types";

import type { OpenUpdateRequest } from "./_components/edit-user-drawer";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { UserLookupForm } from "./_components/user-lookup-form";
import { UserDetailCard } from "./_components/user-detail-card";
import { CreateUserDialog } from "./_components/create-user-dialog";

export const dynamic = "force-dynamic";

interface UsersPageProps {
  searchParams: Promise<{
    type?: string;
    value?: string;
    /**
     * Open a user directly by id, skipping identifier resolution. Needed by
     * the in-app hierarchy links (a supervisor, and each of their reports),
     * which know a user's id but not which identifier to look them up by.
     */
    user_id?: string;
  }>;
}

/** Does this update op still block a new edit (awaiting review)? */
function isOpen(op: UserOperation): boolean {
  return op.status === "PENDING" || op.status === "CHANGES_REQUESTED";
}

/**
 * Find an in-flight update_user request for this user so the detail page can
 * block a duplicate edit. Best-effort — a backend hiccup just drops the guard.
 */
async function findOpenUpdateRequest(
  tenantId: string,
  userId: string,
): Promise<OpenUpdateRequest | null> {
  let ops: UserOperation[] = [];
  try {
    // Both non-terminal statuses count as an open request.
    const [pending, changes] = await Promise.all([
      listUserOperations(tenantId, "PENDING"),
      listUserOperations(tenantId, "CHANGES_REQUESTED"),
    ]);
    ops = [...pending, ...changes];
  } catch (err) {
    if (err instanceof ApiError) return null;
    throw err;
  }
  const match = ops.find(
    (op) =>
      op.operation === "update_user" &&
      isOpen(op) &&
      String(op.payload.target_user_id ?? "") === userId,
  );
  return match ? { id: match.id, status: match.status } : null;
}

export default async function UsersPage({ searchParams }: UsersPageProps) {
  const params = await searchParams;
  const session = await auth();
  // Only platform-admins may release a PIN lockout; the backend also 403s,
  // this just hides the Unlock affordance for other admins.
  const canManageLockout =
    session?.user?.roles?.includes("platform-admin") ?? false;
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Users}
          title="No active tenant"
          description="Switch to a tenant to look up users."
        />
      </div>
    );
  }

  // The assignable user types. Best-effort: a catalog hiccup degrades the type
  // affordances rather than taking the whole page down, since lookup — the
  // reason an operator is here — does not depend on it.
  let catalog: UserTypeCatalog | null = null;
  try {
    catalog = await getUserTypeCatalog(activeTenantId);
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
  }

  let detail: Awaited<ReturnType<typeof getUserDetail>> | null = null;
  let transactions: UserTransaction[] = [];
  let transactionsTotal = 0;
  let reports: UserReport[] = [];
  let reportsTotal = 0;
  let resolvedIdentifierValue: string | null = null;
  let openUpdate: OpenUpdateRequest | null = null;
  let error: ApiError | null = null;
  if (params.user_id || (params.type && params.value)) {
    try {
      // A direct id skips resolution; an identifier lookup resolves first.
      let userId = params.user_id ?? null;
      if (userId === null) {
        const resolved = await resolveIdentifier(
          activeTenantId,
          params.type as string,
          params.value as string,
        );
        userId = resolved.user_id;
        resolvedIdentifierValue = params.value ?? null;
      }
      const resolved = { user_id: userId };
      const [detailRes, txnPage, reportsPage] = await Promise.all([
        getUserDetail(activeTenantId, resolved.user_id),
        listUserTransactions(activeTenantId, resolved.user_id, { limit: 20 }),
        listUserReports(activeTenantId, resolved.user_id, { limit: 50 }),
      ]);
      detail = detailRes;
      transactions = txnPage.items;
      transactionsTotal = txnPage.total;
      reports = reportsPage.items;
      reportsTotal = reportsPage.total;
      openUpdate = await findOpenUpdateRequest(activeTenantId, resolved.user_id);
    } catch (err) {
      if (err instanceof ApiError) error = err;
      else throw err;
    }
  }

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle="Look up by phone, email, account, or card identifier."
        actions={
          <CreateUserDialog
            tenantId={activeTenantId}
            catalog={catalog ?? { categories: [], types: [] }}
            trigger={
              <Button variant="outline">
                <UserPlus className="h-3.5 w-3.5" />
                Register user
              </Button>
            }
          />
        }
      />
      <div className="space-y-6 p-6">
        <UserLookupForm
          initialType={params.type ?? "phone"}
          initialValue={params.value ?? ""}
        />
        {error && (
          <ErrorBanner
            title={error.errorCode === "user_not_found" ? "No user found" : "Lookup failed"}
            description={error.message}
          />
        )}
        {detail && (
          <UserDetailCard
            detail={detail}
            transactions={transactions}
            transactionsTotal={transactionsTotal}
            reports={reports}
            reportsTotal={reportsTotal}
            resolvedIdentifierValue={resolvedIdentifierValue}
            resolvedIdentifierType={params.type ?? "phone"}
            openUpdate={openUpdate}
            canManageLockout={canManageLockout}
            catalog={catalog}
          />
        )}
        {!detail && !error && !params.value && (
          <EmptyState
            icon={Users}
            title="Search for a user"
            description="Pick an identifier type, paste the value, and press Lookup. Phone numbers are normalised — spaces, dashes, and parens are stripped before lookup."
          />
        )}
      </div>
    </div>
  );
}
