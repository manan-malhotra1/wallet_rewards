/**
 * Pricing table (Epic 24 / Story 24.1). Renders pricing configs incl. the
 * slab band and a fee-inclusive indicator. Deleting proposes a DELETE via
 * the maker-checker pipeline — nothing is removed until a second admin
 * approves.
 */
"use client";

import { Trash2 } from "lucide-react";
import * as React from "react";

import { ConfigViewButton } from "@/app/(authenticated)/_components/config-view-button";
import { proposePricingDeleteAction } from "@/app/(authenticated)/pricing/_actions";
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
import type { PricingConfig } from "@/lib/api-types";
import { formatAmount } from "@/lib/utils";

const ACCOUNT_TYPE_LABEL: Record<string, string> = {
  financial_wallet: "Wallet",
  points_account: "Points",
};

/** Render the slab band as "from–to", "≥from", "≤to", or "all". */
function bandLabel(from: string | null, to: string | null): string {
  if (from && to) return `${formatAmount(from)}–${formatAmount(to)}`;
  if (from) return `≥ ${formatAmount(from)}`;
  if (to) return `≤ ${formatAmount(to)}`;
  return "all";
}

export function PricingTable({
  configs,
  tenantId,
}: {
  configs: PricingConfig[];
  tenantId: string;
}) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  const onDelete = async (id: string) => {
    setPending(id);
    const result = await proposePricingDeleteAction(id, tenantId);
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
            <TableHeaderCell>Band</TableHeaderCell>
            <TableHeaderCell className="text-right">Fixed</TableHeaderCell>
            <TableHeaderCell className="text-right">Variable %</TableHeaderCell>
            <TableHeaderCell className="text-right">Fee cap</TableHeaderCell>
            <TableHeaderCell>Fee incl.</TableHeaderCell>
            <TableHeaderCell className="w-[120px] text-right"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {configs.map((cfg) => (
            <TableRow key={cfg.id}>
              <TableCell className="font-medium">
                <Badge variant="info">{cfg.transaction_type}</Badge>
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
              <TableCell className="font-mono text-xs">
                {bandLabel(cfg.amount_from, cfg.amount_to)}
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatAmount(cfg.fixed_fee, { fractionDigits: 2 })}
              </TableCell>
              <TableCell className="text-right font-mono">
                {(parseFloat(cfg.variable_fee_pct) * 100).toFixed(2)}%
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.fee_cap ?? "—"}
              </TableCell>
              <TableCell>
                {cfg.fee_inclusive ? (
                  <Badge variant="secondary">Incl.</Badge>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  <ConfigViewButton
                    configType="pricing"
                    data={cfg as unknown as Record<string, unknown>}
                    title={`Pricing · ${cfg.transaction_type} · ${cfg.currency}`}
                  />
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Propose delete of pricing config"
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
