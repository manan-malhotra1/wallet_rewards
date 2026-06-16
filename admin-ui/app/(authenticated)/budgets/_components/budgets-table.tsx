"use client";

import { Trash2 } from "lucide-react";
import * as React from "react";

import { deleteBudgetAction } from "@/app/(authenticated)/budgets/_actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import type { BudgetConsumption } from "@/lib/api-types";
import { formatAmount, shortId } from "@/lib/utils";

const WINDOW_LABEL: Record<string, string> = {
  rolling_24h: "Rolling 24h",
  rolling_7d: "Rolling 7d",
  calendar_month: "Calendar month",
  lifetime: "Lifetime",
};

function ConsumptionBar({ percent }: { percent: number }) {
  const tone =
    percent >= 100
      ? "bg-destructive"
      : percent >= 80
        ? "bg-amber-500"
        : percent >= 50
          ? "bg-sky-500"
          : "bg-emerald-500";
  const width = Math.min(percent, 100);
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-1.5 w-24 overflow-hidden rounded-full bg-muted">
        <div
          className={`absolute inset-y-0 left-0 ${tone}`}
          style={{ width: `${width}%` }}
        />
      </div>
      <span className="font-mono text-xs tabular text-muted-foreground">
        {percent.toFixed(1)}%
      </span>
    </div>
  );
}

export function BudgetsTable({
  entries,
  tenantId,
}: {
  entries: BudgetConsumption[];
  tenantId: string;
}) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  const onDelete = async (id: string) => {
    setPending(id);
    const result = await deleteBudgetAction(id, tenantId);
    setPending(null);
    if (result.ok) {
      toast({ title: "Budget deleted" });
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
            <TableHeaderCell>Scope</TableHeaderCell>
            <TableHeaderCell>Window</TableHeaderCell>
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell className="text-right">Cap</TableHeaderCell>
            <TableHeaderCell className="text-right">Consumed</TableHeaderCell>
            <TableHeaderCell>Usage</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell className="w-[40px]"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {entries.map(({ budget, consumed_amount, percent_consumed }) => (
            <TableRow key={budget.id}>
              <TableCell>
                {budget.scope_type === "tenant" ? (
                  <Badge variant="default">Tenant-wide</Badge>
                ) : (
                  <Badge variant="info">
                    Rule · {shortId(budget.scope_id ?? "", "rule")}
                  </Badge>
                )}
              </TableCell>
              <TableCell>{WINDOW_LABEL[budget.window_type]}</TableCell>
              <TableCell className="font-mono text-xs">{budget.currency}</TableCell>
              <TableCell className="text-right font-mono">
                {formatAmount(budget.cap_amount, { fractionDigits: 0 })}
              </TableCell>
              <TableCell className="text-right font-mono">
                {formatAmount(consumed_amount, { fractionDigits: 0 })}
              </TableCell>
              <TableCell>
                <ConsumptionBar percent={percent_consumed} />
              </TableCell>
              <TableCell>
                <StatusPill
                  status={budget.status === "active" ? "ACTIVE" : "INACTIVE"}
                  variant="dense"
                />
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Delete budget"
                  disabled={pending === budget.id}
                  onClick={() => onDelete(budget.id)}
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
