/**
 * "Open requests" section for the Service charges page. Lists the tenant's
 * in-flight pricing proposals (PENDING + CHANGES_REQUESTED) so anyone can see a
 * change is under approval. The maker additionally gets an "Edit & resubmit"
 * button (CHANGES_REQUESTED creates only) that opens the create dialog in
 * revise mode; withdraw + version history live on the card itself.
 */
"use client";

import { OpenRequestCard } from "@/app/(authenticated)/_components/open-request-card";
import { Button } from "@/components/ui/button";
import type { ConfigChangeRequest, Instrument, Service } from "@/lib/api-types";

import { CreatePricingDialog } from "./create-pricing-dialog";

export function PricingChangesRequested({
  requests,
  tenantId,
  currentAdminId,
  services,
  instruments,
}: {
  requests: ConfigChangeRequest[];
  tenantId: string;
  currentAdminId: string;
  services: Service[];
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
                <CreatePricingDialog
                  tenantId={tenantId}
                  services={services}
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
