/**
 * "Changes requested" section for the Limits page (Epic 25 / Task 9). Lists
 * sent-back limit proposals. The maker gets an "Edit & resubmit" button that
 * opens the service-limit dialog in revise mode.
 *
 * NOTE: today the Limits page creates configs DIRECTLY (not via maker-checker),
 * so `CHANGES_REQUESTED` limit requests are not produced by this UI in
 * practice; the section is wired for the pipeline should limit writes move
 * behind maker-checker. Wallet-limit proposals are shown read-only (the
 * wallet-limit dialog has no revise variant yet).
 */
"use client";

import { ChangesRequestedCard } from "@/app/(authenticated)/_components/changes-requested-card";
import { Button } from "@/components/ui/button";
import type { ConfigChangeRequest, Instrument, Service } from "@/lib/api-types";

import { CreateLimitDialog } from "./create-limit-dialog";

export function LimitChangesRequested({
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
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-muted-foreground">
        Changes requested
      </h2>
      {requests.map((req) => {
        const canEdit =
          req.maker_admin_id === currentAdminId &&
          req.operation === "create" &&
          req.config_type === "limit";
        return (
          <ChangesRequestedCard
            key={req.id}
            request={req}
            action={
              canEdit ? (
                <CreateLimitDialog
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
