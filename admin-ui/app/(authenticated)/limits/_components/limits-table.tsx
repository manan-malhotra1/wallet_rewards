/**
 * <LimitsTable> — every configured limit in the active tenant.
 * Inline delete via server action; create through the dialog.
 */
"use client";

import { Trash2 } from "lucide-react";
import * as React from "react";

import { deleteLimitConfigAction } from "@/app/(authenticated)/limits/_actions";
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
import type { LimitConfig } from "@/lib/api-types";

const ACCOUNT_TYPE_LABEL: Record<string, string> = {
  financial_wallet: "Wallet",
  points_account: "Points",
};

export function LimitsTable({
  configs,
  tenantId,
}: {
  configs: LimitConfig[];
  tenantId: string;
}) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  const onDelete = async (id: string) => {
    setPending(id);
    const result = await deleteLimitConfigAction(id, tenantId);
    setPending(null);
    if (result.ok) {
      toast({ title: "Limit deleted" });
    } else {
      toast({
        title: "Couldn't delete",
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
            <TableHeaderCell className="text-right">Min</TableHeaderCell>
            <TableHeaderCell className="text-right">Max</TableHeaderCell>
            <TableHeaderCell className="text-right">Daily count</TableHeaderCell>
            <TableHeaderCell className="text-right">Daily value</TableHeaderCell>
            <TableHeaderCell className="text-right">Weekly count</TableHeaderCell>
            <TableHeaderCell className="text-right">Weekly value</TableHeaderCell>
            <TableHeaderCell className="text-right">Monthly count</TableHeaderCell>
            <TableHeaderCell className="text-right">Monthly value</TableHeaderCell>
            <TableHeaderCell className="w-[40px]"> </TableHeaderCell>
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
              <TableCell className="text-right font-mono">
                {cfg.min_amount ?? "—"}
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.max_amount ?? "—"}
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.daily_count_cap ?? "—"}
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.daily_value_cap ?? "—"}
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.weekly_count_cap ?? "—"}
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.weekly_value_cap ?? "—"}
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.monthly_count_cap ?? "—"}
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.monthly_value_cap ?? "—"}
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Delete limit"
                  disabled={pending === cfg.id}
                  onClick={() => onDelete(cfg.id)}
                >
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
