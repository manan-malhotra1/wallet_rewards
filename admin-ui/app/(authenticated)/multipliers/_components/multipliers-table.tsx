/**
 * <MultipliersTable> — every bonus multiplier with factor, scope, window,
 * derived lifecycle status, and a confirm-guarded delete.
 */
"use client";

import { AlertTriangle, Trash2 } from "lucide-react";
import * as React from "react";

import { deleteMultiplierAction } from "@/app/(authenticated)/multipliers/_actions";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import type { BonusMultiplier, Rule, Segment } from "@/lib/api-types";
import {
  deriveMultiplierStatus,
  describeMultiplierScope,
  formatMultiplierFactor,
  formatMultiplierWindow,
} from "@/lib/multiplier-status";
import { formatTimestamp, shortId } from "@/lib/utils";

export function MultipliersTable({
  multipliers,
  rules,
  segments,
}: {
  multipliers: BonusMultiplier[];
  rules: Rule[];
  segments: Segment[];
}) {
  const { toast } = useToast();
  const [confirmTarget, setConfirmTarget] = React.useState<BonusMultiplier | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  // Status is derived against a clock captured once on mount so all rows
  // agree on "now" and re-renders can't flip a pill mid-interaction.
  const [now] = React.useState(() => new Date());
  const ruleName = (id: string | null) =>
    id ? (rules.find((r) => r.id === id)?.name ?? shortId(id)) : null;
  const segmentName = (id: string | null) =>
    id ? (segments.find((s) => s.id === id)?.name ?? shortId(id)) : null;

  const onDelete = async (target: BonusMultiplier) => {
    setSubmitting(true);
    const res = await deleteMultiplierAction(target.id, target.tenant_id);
    setSubmitting(false);
    setConfirmTarget(null);
    if (res.ok) {
      toast({ title: "Multiplier deleted" });
    } else {
      toast({
        title: "Couldn't delete",
        description: `${res.errorCode}: ${res.message}`,
        variant: "danger",
      });
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Factor</TableHeaderCell>
            <TableHeaderCell>Scope</TableHeaderCell>
            <TableHeaderCell>Window</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>Created</TableHeaderCell>
            <TableHeaderCell className="w-[50px]">
              <span className="sr-only">Actions</span>
            </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {multipliers.map((m) => (
            <TableRow key={m.id}>
              <TableCell className="font-mono font-medium tabular-nums">
                {formatMultiplierFactor(m.multiplier)}
              </TableCell>
              <TableCell className="text-sm">
                {describeMultiplierScope(ruleName(m.rule_id), segmentName(m.segment_id))}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatMultiplierWindow(m.valid_from, m.valid_until)}
              </TableCell>
              <TableCell>
                <StatusPill status={deriveMultiplierStatus(m, now)} />
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatTimestamp(m.created_at)}
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Delete multiplier"
                  disabled={submitting}
                  onClick={() => setConfirmTarget(m)}
                >
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog
        open={confirmTarget !== null}
        onOpenChange={(open) => !open && setConfirmTarget(null)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              Delete multiplier?
            </DialogTitle>
            <DialogDescription>
              {confirmTarget && (
                <>
                  <strong>{formatMultiplierFactor(confirmTarget.multiplier)}</strong>{" "}
                  ({describeMultiplierScope(
                    ruleName(confirmTarget.rule_id),
                    segmentName(confirmTarget.segment_id),
                  )}
                  ) stops boosting new rewards immediately. Already-issued
                  rewards keep their boosted value.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmTarget(null)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => confirmTarget && onDelete(confirmTarget)}
              disabled={submitting}
            >
              {submitting ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
