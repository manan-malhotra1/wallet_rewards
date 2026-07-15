/**
 * Tax table (Epic 24 / Story 24.2). Renders tax configs keyed per currency.
 * Deleting proposes a DELETE via the maker-checker pipeline — nothing is
 * removed until a second admin approves.
 */
"use client";

import { Trash2 } from "lucide-react";
import * as React from "react";

import { ConfigViewButton } from "@/app/(authenticated)/_components/config-view-button";
import { proposeTaxDeleteAction } from "@/app/(authenticated)/taxes/_actions";
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
import type { TaxConfig } from "@/lib/api-types";

/** Format a decimal-string rate (e.g. "0.15") as a percentage. */
function pct(value: string): string {
  return `${(parseFloat(value) * 100).toFixed(2)}%`;
}

export function TaxTable({
  configs,
  tenantId,
}: {
  configs: TaxConfig[];
  tenantId: string;
}) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  const onDelete = async (id: string) => {
    setPending(id);
    const result = await proposeTaxDeleteAction(id, tenantId);
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
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell className="text-right">Fee tax</TableHeaderCell>
            <TableHeaderCell>Fee incl.</TableHeaderCell>
            <TableHeaderCell className="text-right">Commission tax</TableHeaderCell>
            <TableHeaderCell>Comm. incl.</TableHeaderCell>
            <TableHeaderCell className="w-[120px] text-right"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {configs.map((cfg) => (
            <TableRow key={cfg.id}>
              <TableCell className="font-mono text-xs">{cfg.currency}</TableCell>
              <TableCell className="text-right font-mono">
                {pct(cfg.fee_tax_pct)}
              </TableCell>
              <TableCell>
                {cfg.fee_tax_inclusive ? (
                  <Badge variant="secondary">Incl.</Badge>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell className="text-right font-mono">
                {pct(cfg.commission_tax_pct)}
              </TableCell>
              <TableCell>
                {cfg.commission_tax_inclusive ? (
                  <Badge variant="secondary">Incl.</Badge>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  <ConfigViewButton
                    configType="tax"
                    data={cfg as unknown as Record<string, unknown>}
                    title={`Tax · ${cfg.currency}`}
                  />
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Propose delete of tax config"
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
