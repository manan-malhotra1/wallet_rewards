/**
 * <StepUpTable> — every configured step-up policy in the active tenant.
 */
"use client";

import { Trash2 } from "lucide-react";
import * as React from "react";

import { deleteStepUpPolicyAction } from "@/app/(authenticated)/step-up/_actions";
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
import type { StepUpPolicy } from "@/lib/api-types";

const TYPE_LABEL: Record<string, string> = {
  p2p: "Peer-to-peer",
  redemption: "Redemption",
};

export function StepUpTable({
  policies,
  tenantId,
}: {
  policies: StepUpPolicy[];
  tenantId: string;
}) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  const onDelete = async (id: string) => {
    setPending(id);
    const result = await deleteStepUpPolicyAction(id, tenantId);
    setPending(null);
    if (result.ok) {
      toast({ title: "Policy deleted" });
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
            <TableHeaderCell>Transaction type</TableHeaderCell>
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell className="text-right">
              Threshold (PIN required above)
            </TableHeaderCell>
            <TableHeaderCell className="w-[40px]"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {policies.map((p) => (
            <TableRow key={p.id}>
              <TableCell className="font-medium">
                <Badge variant="info">
                  {TYPE_LABEL[p.transaction_type] ?? p.transaction_type}
                </Badge>
              </TableCell>
              <TableCell className="font-mono text-xs">{p.currency}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">
                {p.threshold_amount}
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Delete policy"
                  disabled={pending === p.id}
                  onClick={() => onDelete(p.id)}
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
