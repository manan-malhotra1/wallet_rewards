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
  // Wallet limits apply to financial wallets only — offer financial currencies.
  const financialInstruments = instruments.filter(
    (i) => i.account_type === "financial_wallet",
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
        const canEdit =
          req.maker_admin_id === currentAdminId &&
          req.status === "CHANGES_REQUESTED" &&
          req.operation === "create";
        let editAction: ReactNode = undefined;
        if (canEdit && req.config_type === "limit") {
          editAction = (
            <CreateLimitDialog
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
            editAction={editAction}
          />
        );
      })}
    </section>
  );
}
