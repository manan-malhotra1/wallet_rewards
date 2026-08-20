/**
 * "Open requests" section for the Points rates page. Lists the tenant's
 * in-flight conversion-rate proposals (PENDING + CHANGES_REQUESTED) so anyone
 * can see a change is under approval. The maker additionally gets an
 * "Edit & resubmit" button (CHANGES_REQUESTED creates/updates) opening the
 * rate dialog in revise mode.
 */
"use client";

import { OpenRequestCard } from "@/app/(authenticated)/_components/open-request-card";
import { Button } from "@/components/ui/button";
import type { ConfigChangeRequest } from "@/lib/api-types";

import { CreateRateDialog } from "./create-rate-dialog";

export function RatesChangesRequested({
  requests,
  tenantId,
  currentAdminId,
  currencies,
}: {
  requests: ConfigChangeRequest[];
  tenantId: string;
  currentAdminId: string;
  /** The tenant's financial currencies — the revise dialog's options. */
  currencies: string[];
}) {
  if (requests.length === 0) return null;
  return (
    <section className="mb-6 space-y-3">
      <h2 className="text-sm font-semibold text-muted-foreground">
        Open requests
      </h2>
      {requests.map((req) => {
        const canEdit =
          req.maker_admin_id === currentAdminId &&
          req.status === "CHANGES_REQUESTED" &&
          req.operation !== "delete";
        return (
          <OpenRequestCard
            key={req.id}
            request={req}
            tenantId={tenantId}
            currentAdminId={currentAdminId}
            editAction={
              canEdit ? (
                <CreateRateDialog
                  tenantId={tenantId}
                  reviseRequest={req}
                  currencies={currencies}
                  trigger={
                    <Button variant="outline" size="sm">
                      Edit &amp; resubmit
                    </Button>
                  }
                />
              ) : undefined
            }
          />
        );
      })}
    </section>
  );
}
