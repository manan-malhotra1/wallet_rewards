/**
 * "Open requests" section for the Commission page. Lists the tenant's in-flight
 * commission proposals (PENDING + CHANGES_REQUESTED) so anyone can see a change
 * is under approval. The maker additionally gets an "Edit & resubmit" button
 * (CHANGES_REQUESTED creates only) opening the create dialog in revise mode;
 * withdraw + version history live on the card itself.
 */
"use client";

import { OpenRequestCard } from "@/app/(authenticated)/_components/open-request-card";
import { Button } from "@/components/ui/button";
import type {
  ConfigChangeRequest,
  Instrument,
  Service,
  UserTypeCatalog,
} from "@/lib/api-types";

import { CreateCommissionDialog } from "./create-commission-dialog";

export function CommissionChangesRequested({
  requests,
  tenantId,
  currentAdminId,
  services,
  instruments,
  catalog,
}: {
  requests: ConfigChangeRequest[];
  tenantId: string;
  currentAdminId: string;
  services: Service[];
  instruments: Instrument[];
  /** The tenant's user-type catalog, fetched by the page's server component. */
  catalog: UserTypeCatalog;
}) {
  if (requests.length === 0) return null;
  // code → display_name so the card's Service field reads friendly, not raw.
  const serviceNames = Object.fromEntries(
    services.map((s) => [s.code, s.display_name]),
  );
  return (
    <section className="mb-6 space-y-3">
      <h2 className="text-sm font-semibold text-muted-foreground">
        Open requests
      </h2>
      {requests.map((req) => {
        // Both create and update proposals can be revised & resubmitted when a
        // checker sends them back; only deletes carry no editable payload.
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
            serviceNames={serviceNames}
            catalog={catalog}
            editAction={
              canEdit ? (
                <CreateCommissionDialog
                  tenantId={tenantId}
                  services={services}
                  instruments={instruments}
                  catalog={catalog}
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
