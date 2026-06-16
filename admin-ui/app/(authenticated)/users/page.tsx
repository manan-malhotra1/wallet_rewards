/**
 * Users page — identifier lookup → full user detail.
 *
 * On submit the page server-side resolves the identifier to a `user_id`,
 * then fetches the full user-detail payload (identifiers, profile,
 * accounts with balances) and renders the detail card.
 */
import { UserPlus, Users } from "lucide-react";

import { getActiveTenantId } from "@/lib/active-tenant";
import { getUserDetail, resolveIdentifier } from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { UserLookupForm } from "./_components/user-lookup-form";
import { UserDetailCard } from "./_components/user-detail-card";

export const dynamic = "force-dynamic";

interface UsersPageProps {
  searchParams: Promise<{ type?: string; value?: string }>;
}

export default async function UsersPage({ searchParams }: UsersPageProps) {
  const params = await searchParams;
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

  let detail: Awaited<ReturnType<typeof getUserDetail>> | null = null;
  let resolvedIdentifierValue: string | null = null;
  let error: ApiError | null = null;
  if (params.type && params.value) {
    try {
      const resolved = await resolveIdentifier(
        activeTenantId,
        params.type,
        params.value,
      );
      resolvedIdentifierValue = params.value;
      detail = await getUserDetail(activeTenantId, resolved.user_id);
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
          <Button variant="outline" disabled title="Phase G">
            <UserPlus className="h-3.5 w-3.5" />
            Register user
          </Button>
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
            resolvedIdentifierValue={resolvedIdentifierValue}
            resolvedIdentifierType={params.type ?? "phone"}
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
