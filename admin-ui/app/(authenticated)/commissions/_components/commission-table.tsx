/**
 * Commission table (Epic 24 / Story 24.2). Renders commission configs incl.
 * the slab band. Deleting proposes a DELETE via the maker-checker pipeline —
 * nothing is removed until a second admin approves.
 */
"use client";

import { Pencil, Trash2 } from "lucide-react";
import * as React from "react";

import { ConfigViewButton } from "@/app/(authenticated)/_components/config-view-button";
import { proposeCommissionDeleteAction } from "@/app/(authenticated)/commissions/_actions";
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
import type { CommissionConfig, Instrument, Service } from "@/lib/api-types";
import { serviceLabel } from "@/lib/service-label";
import { formatAmount, formatCap } from "@/lib/utils";

import { CreateCommissionDialog } from "./create-commission-dialog";

/** Render the slab band as "from–to", "≥from", "≤to", or "all". */
function bandLabel(from: string | null, to: string | null): string {
  if (from && to) return `${formatAmount(from)}–${formatAmount(to)}`;
  if (from) return `≥ ${formatAmount(from)}`;
  if (to) return `≤ ${formatAmount(to)}`;
  return "all";
}

/**
 * Per-row Edit affordance — opens the create dialog in edit mode (proposes an
 * `update`). Self-contained so it composes with a tooltip.
 */
function EditCommissionButton({
  cfg,
  tenantId,
  services,
  instruments,
}: {
  cfg: CommissionConfig;
  tenantId: string;
  services: Service[];
  instruments: Instrument[];
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Tooltip content="Edit">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Edit commission config"
          onClick={() => setOpen(true)}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      </Tooltip>
      <CreateCommissionDialog
        tenantId={tenantId}
        services={services}
        instruments={instruments}
        editConfig={cfg}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}

export function CommissionTable({
  configs,
  tenantId,
  services,
  instruments,
  canPropose,
  serviceNames,
}: {
  configs: CommissionConfig[];
  tenantId: string;
  services: Service[];
  instruments: Instrument[];
  /** platform-admin gate — hides the Edit affordance for other admins. */
  canPropose: boolean;
  /** `{ code: display_name }` forwarded to the View drawer. */
  serviceNames?: Record<string, string>;
}) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  const onDelete = async (id: string) => {
    setPending(id);
    const result = await proposeCommissionDeleteAction(id, tenantId);
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
            <TableHeaderCell>Txn type</TableHeaderCell>
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell>User type</TableHeaderCell>
            <TableHeaderCell>Band</TableHeaderCell>
            <TableHeaderCell className="text-right">Fixed</TableHeaderCell>
            <TableHeaderCell className="text-right">Variable %</TableHeaderCell>
            <TableHeaderCell className="text-right">Cap</TableHeaderCell>
            <TableHeaderCell className="w-[120px] text-right"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {configs.map((cfg) => (
            <TableRow key={cfg.id}>
              <TableCell className="font-medium">
                <Badge variant="info">
                  {serviceLabel(cfg.transaction_type, serviceNames)}
                </Badge>
              </TableCell>
              <TableCell className="font-mono text-xs">{cfg.currency}</TableCell>
              <TableCell>
                {cfg.user_type ? (
                  <UserTypeBadge type={cfg.user_type} />
                ) : (
                  <span className="text-xs text-muted-foreground">All types</span>
                )}
              </TableCell>
              <TableCell className="font-mono text-xs">
                {bandLabel(cfg.amount_from, cfg.amount_to)}
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatAmount(cfg.fixed_commission, { fractionDigits: 2 })}
              </TableCell>
              <TableCell className="text-right font-mono">
                {(parseFloat(cfg.variable_commission_pct) * 100).toFixed(2)}%
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatCap(cfg.commission_cap)}
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  <ConfigViewButton
                    configType="commission"
                    data={cfg as unknown as Record<string, unknown>}
                    title={`Commission · ${serviceLabel(cfg.transaction_type, serviceNames)} · ${cfg.currency}`}
                    serviceNames={serviceNames}
                  />
                  {canPropose && (
                    <EditCommissionButton
                      cfg={cfg}
                      tenantId={tenantId}
                      services={services}
                      instruments={instruments}
                    />
                  )}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Propose delete of commission config"
                    disabled={pending === cfg.id}
                    onClick={() => onDelete(cfg.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
