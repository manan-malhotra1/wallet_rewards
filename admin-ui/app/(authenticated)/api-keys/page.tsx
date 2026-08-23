/**
 * API keys page (Epic 14 S2) — per-tenant credentials for the external
 * user-creation API. Create reveals the secret once; revoke disables a key.
 */
import { KeyRound, Plus } from "lucide-react";

import { ApiError } from "@/lib/api";
import { getActiveTenantId } from "@/lib/active-tenant";
import { getUserTypeCatalog, listApiKeys } from "@/lib/api-endpoints";
import type { ApiKey, UserTypeCatalog } from "@/lib/api-types";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { ApiKeysTable } from "./_components/api-keys-table";
import { CreateApiKeyDialog } from "./_components/create-api-key-dialog";

export const dynamic = "force-dynamic";

const NEW_BUTTON_CLASS =
  "inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90";

export default async function ApiKeysPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={KeyRound}
          title="No active tenant"
          description="Switch to a tenant to manage its API keys."
        />
      </div>
    );
  }

  let keys: ApiKey[] = [];
  // Which types may back a cash-in key is runtime data
  // (`requires_merchant_profile`), so the dialog needs the catalog to judge a
  // resolved user rather than matching against a hardcoded pair of codes.
  let catalog: UserTypeCatalog = { categories: [], types: [] };
  let error: ApiError | null = null;
  try {
    [keys, catalog] = await Promise.all([
      listApiKeys(activeTenantId),
      getUserTypeCatalog(activeTenantId),
    ]);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="API keys"
        subtitle="Per-tenant credentials for the external user-creation API. Partners sign requests with the key secret (HMAC); the secret is shown only once, at creation."
        actions={
          <CreateApiKeyDialog
            tenantId={activeTenantId}
            catalog={catalog}
            trigger={
              <button type="button" className={NEW_BUTTON_CLASS}>
                <Plus className="h-3.5 w-3.5" />
                New key
              </button>
            }
          />
        }
      />
      <div className="space-y-6 p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load API keys"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && keys.length === 0 ? (
          <EmptyState
            icon={KeyRound}
            title="No API keys"
            description="Create a key to let a partner call POST /api/v1/external/users for this tenant."
          />
        ) : (
          <ApiKeysTable keys={keys} tenantId={activeTenantId} />
        )}
      </div>
    </div>
  );
}
