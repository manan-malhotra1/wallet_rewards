/**
 * "Changes requested" section for the Service charges page (Epic 25 / Task 9).
 * Lists the maker's sent-back pricing proposals; the maker gets an
 * "Edit & resubmit" button that opens the create dialog in revise mode.
 */
"use client";

import { ChangesRequestedCard } from "@/app/(authenticated)/_components/changes-requested-card";
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
        Changes requested
      </h2>
      {requests.map((req) => (
        <ChangesRequestedCard
          key={req.id}
          request={req}
          action={
            req.maker_admin_id === currentAdminId &&
            req.operation === "create" ? (
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
      ))}
    </section>
  );
}
