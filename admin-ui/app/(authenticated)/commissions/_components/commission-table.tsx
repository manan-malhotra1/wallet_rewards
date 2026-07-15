/**
 * Commission table (Epic 24 / Story 24.2). Renders commission configs incl.
 * the slab band. Deleting proposes a DELETE via the maker-checker pipeline —
 * nothing is removed until a second admin approves.
 */
"use client";

import { Trash2 } from "lucide-react";
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
import { useToast } from "@/components/ui/toast";
import type { CommissionConfig } from "@/lib/api-types";
import { formatAmount } from "@/lib/utils";

/** Render the slab band as "from–to", "≥from", "≤to", or "all". */
function bandLabel(from: string | null, to: string | null): string {
  if (from && to) return `${formatAmount(from)}–${formatAmount(to)}`;
  if (from) return `≥ ${formatAmount(from)}`;
  if (to) return `≤ ${formatAmount(to)}`;
  return "all";
}

export function CommissionTable({
  configs,
  tenantId,
}: {
  configs: CommissionConfig[];
  tenantId: string;
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
                <Badge variant="info">{cfg.transaction_type}</Badge>
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
                {cfg.commission_cap ?? "—"}
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  <ConfigViewButton
                    configType="commission"
                    data={cfg as unknown as Record<string, unknown>}
                    title={`Commission · ${cfg.transaction_type} · ${cfg.currency}`}
                  />
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
