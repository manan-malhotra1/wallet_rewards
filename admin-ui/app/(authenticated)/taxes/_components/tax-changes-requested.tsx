/**
 * "Open requests" section for the Taxes page. Lists the tenant's in-flight tax
 * proposals (PENDING + CHANGES_REQUESTED) so anyone can see a change is under
 * approval. The maker additionally gets an "Edit & resubmit" button
 * (CHANGES_REQUESTED creates only) opening the create dialog in revise mode;
 * withdraw + version history live on the card itself.
 */
"use client";

import { OpenRequestCard } from "@/app/(authenticated)/_components/open-request-card";
import { Button } from "@/components/ui/button";
import type { ConfigChangeRequest, Instrument } from "@/lib/api-types";

import { CreateTaxDialog } from "./create-tax-dialog";

export function TaxChangesRequested({
  requests,
  tenantId,
  currentAdminId,
  instruments,
}: {
  requests: ConfigChangeRequest[];
  tenantId: string;
  currentAdminId: string;
  instruments: Instrument[];
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
          req.operation === "create";
        return (
          <OpenRequestCard
            key={req.id}
            request={req}
            tenantId={tenantId}
            currentAdminId={currentAdminId}
            editAction={
              canEdit ? (
                <CreateTaxDialog
                  tenantId={tenantId}
                  instruments={instruments}
                  reviseRequest={req}
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
