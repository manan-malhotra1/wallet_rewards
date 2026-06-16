/**
 * Users page — identifier search + result list.
 *
 * The backend doesn't have a "list users" endpoint yet (Phase G); for now
 * the page is identifier-lookup-driven: enter a phone/email/account/card
 * and the server resolves it via Pay-PRD-0060. Results render as cards
 * with a "View detail" drawer trigger.
 */
import { UserPlus, Users } from "lucide-react";

import { getActiveTenantId } from "@/lib/active-tenant";
import { resolveIdentifier } from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { UserLookupForm } from "./_components/user-lookup-form";
import { ResolvedUserCard } from "./_components/resolved-user-card";

export const dynamic = "force-dynamic";

interface UsersPageProps {
  searchParams: Promise<{ type?: string; value?: string }>;
}

export default async function UsersPage({ searchParams }: UsersPageProps) {
  const params = await searchParams;
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="px-6 py-8">
        <EmptyState
          icon={Users}
          title="No active tenant"
          description="Switch to a tenant to look up users."
        />
      </div>
    );
  }

  let resolved: Awaited<ReturnType<typeof resolveIdentifier>> | null = null;
  let error: ApiError | null = null;
  if (params.type && params.value) {
    try {
      resolved = await resolveIdentifier(activeTenantId, params.type, params.value);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err;
      } else {
        throw err;
      }
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
      <div className="px-6 py-6">
        <UserLookupForm
          initialType={params.type ?? "phone"}
          initialValue={params.value ?? ""}
        />
        <div className="mt-6">
          {error && (
            <ErrorBanner
              title={error.errorCode === "user_not_found" ? "No user found" : "Lookup failed"}
              description={error.message}
            />
          )}
          {resolved && (
            <ResolvedUserCard
              userId={resolved.user_id}
              tenantId={resolved.tenant_id}
              identifierType={resolved.identifier_type}
              identifierValue={params.value ?? ""}
            />
          )}
          {!resolved && !error && !params.value && (
            <EmptyState
              icon={Users}
              title="Search for a user"
              description="Pick an identifier type, paste the value, and press Lookup. Full user-listing tables land in Phase G."
            />
          )}
        </div>
      </div>
    </div>
  );
}
