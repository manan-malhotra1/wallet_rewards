/**
 * Pricing table (Epic 24 / Story 24.1; Epic 25 Pass 1). Renders ONE row per
 * pricing CONFIG (scope), not one per band — the bands of a schedule live
 * inside the View drawer and the Edit dialog. Deleting proposes a DELETE of the
 * whole scope via the maker-checker pipeline; nothing is removed until a second
 * admin approves.
 */
"use client";

import { Pencil, Trash2 } from "lucide-react";
import * as React from "react";

import { ChangeProposedTooltip } from "@/app/(authenticated)/_components/change-proposed-tooltip";
import { ConfigStatusPill } from "@/app/(authenticated)/_components/config-status-pill";
import { ConfigViewButton } from "@/app/(authenticated)/_components/config-view-button";
import { proposePricingDeleteAction } from "@/app/(authenticated)/pricing/_actions";
import { configScopeKey } from "@/lib/config-scope";
import { UserTypeBadge } from "@/app/(authenticated)/users/_components/user-type-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { Tooltip } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";
import type { Instrument, PricingConfigGroup, Service } from "@/lib/api-types";
import { serviceLabel } from "@/lib/service-label";
import { formatAmount } from "@/lib/utils";

import { CreatePricingDialog } from "./create-pricing-dialog";

const ACCOUNT_TYPE_LABEL: Record<string, string> = {
  financial_wallet: "Wallet",
  points_account: "Points",
};

/**
 * Render one band's range compactly: "0–1,000", "5,000+" (open-ended top), or
 * "≤ 1,000" (open-ended bottom). Amounts use 2-decimal thousands formatting.
 */
function bandRange(from: string | null, to: string | null): string {
  const f = from ? formatAmount(from) : null;
  const t = to ? formatAmount(to) : null;
  if (f && t) return `${f}–${t}`;
  if (f) return `${f}+`;
  if (t) return `≤ ${t}`;
  return "all";
}

export function PricingTable({
  groups,
  tenantId,
  services,
  instruments,
  canPropose,
  serviceNames,
  changeProposedKeys,
}: {
  groups: PricingConfigGroup[];
  tenantId: string;
  services: Service[];
  instruments: Instrument[];
  /** platform-admin gate — hides the Edit affordance for other admins. */
  canPropose: boolean;
  /** `{ code: display_name }` forwarded to the View drawer. */
  serviceNames?: Record<string, string>;
  /** Scope keys with an open update/delete request → "change proposed" status. */
  changeProposedKeys: ReadonlySet<string>;
}) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  // Delete acts on the whole schedule; the backend removes every band of the
  // scope keyed off the first band's id.
  const onDelete = async (group: PricingConfigGroup) => {
    if (
      !window.confirm(
        `Propose deleting this whole schedule (${group.bands.length} band${group.bands.length === 1 ? "" : "s"})?`,
      )
    ) {
      return;
    }
    setPending(group.key);
    const result = await proposePricingDeleteAction(group.bands[0].id, tenantId);
    setPending(null);
    if (result.ok) {
      toast({ title: "Delete proposed — pending approval" });
    } else {
      toast({
        title: "Couldn't propose delete",
        description: `${result.errorCode}: ${result.message}`,
        variant: "danger",
      });
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Service</TableHeaderCell>
            <TableHeaderCell>Account</TableHeaderCell>
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell>User type</TableHeaderCell>
            <TableHeaderCell>Bands</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell className="w-[120px] text-right"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {groups.map((group) => {
            const name = serviceLabel(group.transaction_type, serviceNames);
            const ranges = group.bands
              .map((b) => bandRange(b.amount_from, b.amount_to))
              .join(" · ");
            const count = group.bands.length;
            // A scope with an open request can't take another Edit / Delete /
            // restore — those affordances are disabled until it's resolved.
            const changeProposed = changeProposedKeys.has(
              configScopeKey("pricing", group),
            );
            return (
              <TableRow key={group.key}>
                <TableCell className="font-medium">
                  <Badge variant="info">{name}</Badge>
                </TableCell>
                <TableCell>
                  {ACCOUNT_TYPE_LABEL[group.account_type] ?? group.account_type}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {group.currency}
                </TableCell>
                <TableCell>
                  {group.user_type ? (
                    <UserTypeBadge type={group.user_type} />
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      All types
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex flex-col">
                    <span className="text-xs font-medium">
                      {count} band{count === 1 ? "" : "s"}
                    </span>
                    <span
                      className="max-w-[240px] truncate font-mono text-[11px] text-muted-foreground"
                      title={ranges}
                    >
                      {ranges}
                    </span>
                  </div>
                </TableCell>
                <TableCell>
                  <ConfigStatusPill changeProposed={changeProposed} />
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-1">
                    <ConfigViewButton
                      configType="pricing"
                      data={{ bands: group.bands }}
                      title={`Pricing · ${name} · ${group.currency}`}
                      serviceNames={serviceNames}
                      tenantId={tenantId}
                      targetConfigId={group.bands[0].id}
                      canPropose={canPropose}
                      changeProposed={changeProposed}
                    />
                    {canPropose && (
                      <EditPricingButton
                        group={group}
                        tenantId={tenantId}
                        services={services}
                        instruments={instruments}
                        changeProposed={changeProposed}
                      />
                    )}
                    {changeProposed ? (
                      <ChangeProposedTooltip>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label="Propose delete of pricing schedule"
                          disabled
                        >
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </ChangeProposedTooltip>
                    ) : (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Propose delete of pricing schedule"
                        disabled={pending === group.key}
                        onClick={() => onDelete(group)}
                      >
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * Per-row Edit affordance — opens the create dialog in edit mode (proposes an
 * `update`) prefilled with the whole schedule's bands. Self-contained: owns its
 * open state so it composes with a tooltip without fighting the dialog trigger.
 */
function EditPricingButton({
  group,
  tenantId,
  services,
  instruments,
  changeProposed,
}: {
  group: PricingConfigGroup;
  tenantId: string;
  services: Service[];
  instruments: Instrument[];
  /** Open request on this scope → disable Edit; the maker resolves it first. */
  changeProposed: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  if (changeProposed) {
    return (
      <ChangeProposedTooltip>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Edit pricing schedule"
          disabled
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      </ChangeProposedTooltip>
    );
  }
  return (
    <>
      <Tooltip content="Edit">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Edit pricing schedule"
          onClick={() => setOpen(true)}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      </Tooltip>
      <CreatePricingDialog
        tenantId={tenantId}
        services={services}
        instruments={instruments}
        editGroup={group}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}
