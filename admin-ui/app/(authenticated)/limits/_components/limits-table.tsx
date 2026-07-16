/**
 * <LimitsTable> — every configured limit in the active tenant. Deleting
 * PROPOSES a delete through the maker-checker pipeline; the row is removed only
 * once a second admin approves. Create through the dialog (also propose).
 */
"use client";

import { Pencil, Trash2 } from "lucide-react";
import * as React from "react";

import { ConfigStatusPill } from "@/app/(authenticated)/_components/config-status-pill";
import { ConfigViewButton } from "@/app/(authenticated)/_components/config-view-button";
import { proposeLimitDeleteAction } from "@/app/(authenticated)/limits/_actions";
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
import type { Instrument, LimitConfig, Service } from "@/lib/api-types";
import { serviceLabel } from "@/lib/service-label";
import { formatCap } from "@/lib/utils";

import { CreateLimitDialog } from "./create-limit-dialog";

const ACCOUNT_TYPE_LABEL: Record<string, string> = {
  financial_wallet: "Wallet",
  points_account: "Points",
};

/**
 * Per-row Edit affordance — opens the create dialog in edit mode (proposes an
 * `update`). Self-contained so it composes with a tooltip.
 */
function EditLimitButton({
  cfg,
  tenantId,
  services,
  instruments,
}: {
  cfg: LimitConfig;
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
          aria-label="Edit limit"
          onClick={() => setOpen(true)}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      </Tooltip>
      <CreateLimitDialog
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

export function LimitsTable({
  configs,
  tenantId,
  services,
  instruments,
  canPropose,
  serviceNames,
  changeProposedKeys,
}: {
  configs: LimitConfig[];
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

  const onDelete = async (id: string) => {
    setPending(id);
    const result = await proposeLimitDeleteAction(id, tenantId);
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
            <TableHeaderCell>Account</TableHeaderCell>
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell>User type</TableHeaderCell>
            <TableHeaderCell className="text-right">Min</TableHeaderCell>
            <TableHeaderCell className="text-right">Max</TableHeaderCell>
            <TableHeaderCell className="text-right">Daily count</TableHeaderCell>
            <TableHeaderCell className="text-right">Daily value</TableHeaderCell>
            <TableHeaderCell className="text-right">Weekly count</TableHeaderCell>
            <TableHeaderCell className="text-right">Weekly value</TableHeaderCell>
            <TableHeaderCell className="text-right">Monthly count</TableHeaderCell>
            <TableHeaderCell className="text-right">Monthly value</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
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
              <TableCell>
                {ACCOUNT_TYPE_LABEL[cfg.account_type] ?? cfg.account_type}
              </TableCell>
              <TableCell className="font-mono text-xs">{cfg.currency}</TableCell>
              <TableCell>
                {cfg.user_type ? (
                  <UserTypeBadge type={cfg.user_type} />
                ) : (
                  <span className="text-xs text-muted-foreground">All types</span>
                )}
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatCap(cfg.min_amount)}
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatCap(cfg.max_amount)}
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.daily_count_cap ?? "—"}
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatCap(cfg.daily_value_cap)}
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.weekly_count_cap ?? "—"}
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatCap(cfg.weekly_value_cap)}
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.monthly_count_cap ?? "—"}
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatCap(cfg.monthly_value_cap)}
              </TableCell>
              <TableCell>
                <ConfigStatusPill
                  changeProposed={changeProposedKeys.has(
                    configScopeKey("limit", cfg as unknown as Record<string, unknown>),
                  )}
                />
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  <ConfigViewButton
                    configType="limit"
                    data={cfg as unknown as Record<string, unknown>}
                    title={`Limit · ${serviceLabel(cfg.transaction_type, serviceNames)} · ${cfg.currency}`}
                    serviceNames={serviceNames}
                    tenantId={tenantId}
                    targetConfigId={cfg.id}
                    canPropose={canPropose}
                  />
                  {canPropose && (
                    <EditLimitButton
                      cfg={cfg}
                      tenantId={tenantId}
                      services={services}
                      instruments={instruments}
                    />
                  )}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Propose delete of limit"
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
