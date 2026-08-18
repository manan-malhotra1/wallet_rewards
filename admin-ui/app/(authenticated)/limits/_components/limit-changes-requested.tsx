/**
 * "Open requests" section for the Limits page. Lists the tenant's in-flight
 * limit + wallet-limit proposals (PENDING + CHANGES_REQUESTED) so anyone can
 * see a change is under approval. The maker additionally gets an "Edit &
 * resubmit" button (CHANGES_REQUESTED creates only) opening the matching revise
 * dialog per config type; withdraw + version history live on the card itself.
 */
"use client";

import type { ReactNode } from "react";

import { OpenRequestCard } from "@/app/(authenticated)/_components/open-request-card";
import { Button } from "@/components/ui/button";
import type { ConfigChangeRequest, Instrument, Service } from "@/lib/api-types";

import { CreateLimitDialog } from "./create-limit-dialog";
import { CreateWalletLimitDialog } from "./create-wallet-limit-dialog";

export function LimitChangesRequested({
  requests,
  tenantId,
  pointsAvailable,
  currentAdminId,
  services,
  instruments,
}: {
  requests: ConfigChangeRequest[];
  tenantId: string;
  /** Threaded to the dialog: points options need a points programme (B6.1). */
  pointsAvailable: boolean;
  currentAdminId: string;
  services: Service[];
  instruments: Instrument[];
}) {
  if (requests.length === 0) return null;
  // Wallet limits apply to financial wallets only — offer financial currencies.
  const financialInstruments = instruments.filter(
    (i) => i.account_type === "financial_wallet",
  );
  // code → display_name so a limit card's Service field reads friendly.
  const serviceNames = Object.fromEntries(
    services.map((s) => [s.code, s.display_name]),
  );

  const editTrigger = (
    <Button variant="outline" size="sm">
      Edit &amp; resubmit
    </Button>
  );

  return (
    <section className="space-y-3">
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
        let editAction: ReactNode = undefined;
        if (canEdit && req.config_type === "limit") {
          editAction = (
            <CreateLimitDialog
        pointsAvailable={pointsAvailable}
              tenantId={tenantId}
              services={services}
              instruments={instruments}
              reviseRequest={req}
              trigger={editTrigger}
            />
          );
        } else if (canEdit && req.config_type === "wallet_limit") {
          editAction = (
            <CreateWalletLimitDialog
              tenantId={tenantId}
              instruments={financialInstruments}
              reviseRequest={req}
              trigger={editTrigger}
            />
          );
        }
        return (
          <OpenRequestCard
            key={req.id}
            request={req}
            tenantId={tenantId}
            currentAdminId={currentAdminId}
            serviceNames={serviceNames}
            editAction={editAction}
          />
        );
      })}
    </section>
  );
}
