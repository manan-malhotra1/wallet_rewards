/**
 * "Changes requested" section for the Taxes page (Epic 25 / Task 9). Lists the
 * maker's sent-back tax proposals; the maker gets an "Edit & resubmit" button
 * that opens the create dialog in revise mode.
 */
"use client";

import { ChangesRequestedCard } from "@/app/(authenticated)/_components/changes-requested-card";
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
        Changes requested
      </h2>
      {requests.map((req) => (
        <ChangesRequestedCard
          key={req.id}
          request={req}
          action={
            req.maker_admin_id === currentAdminId &&
            req.operation === "create" ? (
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
      ))}
    </section>
  );
}
