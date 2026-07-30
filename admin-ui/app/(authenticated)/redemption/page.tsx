/**
 * Redemption page — provider configuration + manual review queue.
 *
 * Two tabs:
 *  - Providers: list registered providers (admin can register a new one
 *    with a shared_secret for HMAC callbacks)
 *  - Manual review: stuck redemptions awaiting operator resolution
 */
import { CreditCard, Plus } from "lucide-react";

import { getActiveTenantId } from "@/lib/active-tenant";
import { listManualReview } from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { ManualReviewTable } from "./_components/manual-review-table";
import { RegisterProviderDialog } from "./_components/register-provider-dialog";

export const dynamic = "force-dynamic";

export default async function RedemptionPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="px-6 py-8">
        <EmptyState
          icon={CreditCard}
          title="No active tenant"
          description="Switch to a tenant to see its redemption providers."
        />
      </div>
    );
  }

  let manualReview: Awaited<ReturnType<typeof listManualReview>> = [];
  let error: ApiError | null = null;
  try {
    manualReview = await listManualReview(activeTenantId);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Redemption"
        subtitle="Configure cash-out / voucher providers and resolve stuck redemptions."
        actions={
          <RegisterProviderDialog
            tenantId={activeTenantId}
            trigger={
              <button
                type="button"
                className="inline-flex h-8 items-center gap-2 rounded-md bg-[--color-brand] px-3 text-[13px] font-medium text-[--color-brand-foreground] hover:opacity-90"
              >
                <Plus className="h-3.5 w-3.5" />
                Register provider
              </button>
            }
          />
        }
      />
      <div className="px-6 py-6">
        {error && (
          <ErrorBanner className="mb-4" title="Couldn't load queue" description={error.message} />
        )}
        <Tabs defaultValue="manual">
          <TabsList>
            <TabsTrigger value="manual">
              Manual review ({manualReview.length})
            </TabsTrigger>
            <TabsTrigger value="providers">Providers</TabsTrigger>
          </TabsList>
          <TabsContent value="manual">
            {manualReview.length === 0 ? (
              <EmptyState
                icon={CreditCard}
                title="Queue empty"
                description="No redemptions are stuck. The reconciliation sweep moves anything that exceeds retries here."
              />
            ) : (
              <ManualReviewTable items={manualReview} />
            )}
          </TabsContent>
          <TabsContent value="providers">
            <EmptyState
              icon={CreditCard}
              title="Provider list"
              description="The backend doesn't expose a list-providers endpoint yet (Phase G). Registration works via the button above and the audit log records each provider as it's added."
            />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
