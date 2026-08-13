/**
 * <StepUpTable> — every configured step-up policy in the active tenant.
 *
 * Edit / Delete now PROPOSE a change through the maker-checker pipeline (the
 * direct step-up endpoints were retired). A policy whose scope already has an
 * open proposal shows "Active · change proposed" and its Edit / Delete are
 * disabled until that proposal resolves.
 */
"use client";

import { Pencil, Trash2 } from "lucide-react";
import * as React from "react";

import { ChangeProposedTooltip } from "@/app/(authenticated)/_components/change-proposed-tooltip";
import { ConfigStatusPill } from "@/app/(authenticated)/_components/config-status-pill";
import { ConfigViewButton } from "@/app/(authenticated)/_components/config-view-button";
import { proposeStepUpDeleteAction } from "@/app/(authenticated)/step-up/_actions";
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
import type { StepUpPolicy } from "@/lib/api-types";
import { configScopeKey } from "@/lib/config-scope";

import { CreateStepUpDialog } from "./create-step-up-dialog";

const TYPE_LABEL: Record<string, string> = {
  p2p: "Peer-to-peer",
  redemption: "Redemption",
};

/**
 * Per-row Edit affordance — opens the create dialog in edit mode (proposes an
 * `update`). Self-contained so it composes with a tooltip.
 */
function EditStepUpButton({
  policy,
  tenantId,
  changeProposed,
}: {
  policy: StepUpPolicy;
  tenantId: string;
  /** Open request on this scope → disable Edit; the maker resolves it first. */
  changeProposed: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  if (changeProposed) {
    return (
      <ChangeProposedTooltip>
        <Button variant="ghost" size="icon-sm" aria-label="Edit policy" disabled>
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
          aria-label="Edit policy"
          onClick={() => setOpen(true)}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      </Tooltip>
      <CreateStepUpDialog
        tenantId={tenantId}
        editPolicy={policy}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}

export function StepUpTable({
  policies,
  tenantId,
  canPropose,
  changeProposedKeys,
}: {
  policies: StepUpPolicy[];
  tenantId: string;
  /** platform-admin gate — hides the Edit/Delete affordances for other admins. */
  canPropose: boolean;
  /** Scope keys with an open update/delete request → "change proposed" status. */
  changeProposedKeys: ReadonlySet<string>;
}) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  const onDelete = async (id: string) => {
    setPending(id);
    const result = await proposeStepUpDeleteAction(id, tenantId);
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
    <div className="glass-panel overflow-hidden rounded-lg">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Transaction type</TableHeaderCell>
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell className="text-right">
              Threshold (PIN required above)
            </TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell className="w-[120px] text-right"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {policies.map((p) => {
            // A scope with an open request can't take another Edit / Delete —
            // those affordances are disabled until it's resolved.
            const changeProposed = changeProposedKeys.has(
              configScopeKey("step_up", p as unknown as Record<string, unknown>),
            );
            return (
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
                  <ConfigStatusPill changeProposed={changeProposed} />
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-1">
                    <ConfigViewButton
                      configType="step_up"
                      data={p as unknown as Record<string, unknown>}
                      title={`Step-up · ${p.transaction_type} · ${p.currency}`}
                      tenantId={tenantId}
                      targetConfigId={p.id}
                      canPropose={canPropose}
                      changeProposed={changeProposed}
                    />
                    {canPropose && (
                      <EditStepUpButton
                        policy={p}
                        tenantId={tenantId}
                        changeProposed={changeProposed}
                      />
                    )}
                    {canPropose &&
                      (changeProposed ? (
                        <ChangeProposedTooltip>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label="Propose delete of policy"
                            disabled
                          >
                            <Trash2 className="h-3.5 w-3.5 text-destructive" />
                          </Button>
                        </ChangeProposedTooltip>
                      ) : (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label="Propose delete of policy"
                          disabled={pending === p.id}
                          onClick={() => onDelete(p.id)}
                        >
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      ))}
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
