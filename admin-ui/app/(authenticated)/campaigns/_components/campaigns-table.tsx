/**
 * <CampaignsTable> — dense table of every campaign in the active tenant
 * plus its performance, budget scope, and per-row View / Edit / Delete.
 *
 * Hovering the campaign name surfaces a tooltip with the plain-English
 * description (trigger + reward + recurrence + budget scope).
 */
"use client";

import { Eye, Info, Pencil, Trash2 } from "lucide-react";
import * as React from "react";

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
import { Tooltip } from "@/components/ui/tooltip";
import type { Rule, RulePerformance, Segment, SegmentGroup } from "@/lib/api-types";
import { formatAmount } from "@/lib/utils";

import { describeBudgetScope, describeCampaignFull } from "../_lib/describe-campaign";
import { CampaignDetailDrawer } from "./campaign-detail-drawer";
import { DeleteCampaignDialog } from "./delete-campaign-dialog";
import { EditCampaignDialog } from "./edit-campaign-dialog";

/** Friendlier labels — also relabels the "campaign" sub-type as "Time-boxed"
 * so it doesn't collide with the parent Campaign concept. */
const TYPE_LABEL: Record<Rule["rule_type"], string> = {
  milestone: "Milestone",
  streak: "Streak",
  first_time: "First-time",
  value_based: "Value-based",
  composite: "Composite",
  campaign: "Time-boxed",
  referral: "Referral",
};

const BUDGET_BADGE: Record<
  RulePerformance["budget_scope"],
  { label: string; tone: "neutral" | "accent" | "brand" }
> = {
  none: { label: "Uncapped", tone: "neutral" },
  tenant_only: { label: "Tenant only", tone: "accent" },
  rule_only: { label: "Per-campaign", tone: "accent" },
  both: { label: "Both", tone: "brand" },
};

type ActiveAction = {
  rule: Rule;
  performance: RulePerformance | null;
  action: "view" | "edit" | "delete";
};

export function CampaignsTable({
  rules,
  performance,
  tenantId,
  segments,
  segmentGroups,
}: {
  rules: Rule[];
  performance: Record<string, RulePerformance | null>;
  tenantId: string;
  segments: Segment[];
  segmentGroups: SegmentGroup[];
}) {
  const [active, setActive] = React.useState<ActiveAction | null>(null);

  const close = () => setActive(null);

  return (
    <div className="overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface-1]">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Name</TableHeaderCell>
            <TableHeaderCell className="text-center">Type</TableHeaderCell>
            <TableHeaderCell className="text-center">Trigger</TableHeaderCell>
            <TableHeaderCell className="text-center">Reward</TableHeaderCell>
            <TableHeaderCell className="text-center">Budget</TableHeaderCell>
            <TableHeaderCell className="text-center">Fires</TableHeaderCell>
            <TableHeaderCell className="text-center">Unique users</TableHeaderCell>
            <TableHeaderCell className="text-center">Status</TableHeaderCell>
            <TableHeaderCell className="text-center">Actions</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rules.map((rule) => {
            const perf = performance[rule.id];
            const lines = describeCampaignFull(rule, perf);
            const budget = perf ? BUDGET_BADGE[perf.budget_scope] : BUDGET_BADGE.none;
            return (
              <TableRow key={rule.id}>
                <TableCell className="font-medium">
                  <div className="flex items-center gap-1.5">
                    <span>{rule.name}</span>
                    <Tooltip
                      content={
                        <div className="space-y-1.5 leading-relaxed">
                          {lines.map((line, i) => (
                            <p key={i}>{line}</p>
                          ))}
                        </div>
                      }
                    >
                      <button
                        type="button"
                        aria-label="Campaign details"
                        className="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground hover:text-foreground"
                      >
                        <Info className="h-3.5 w-3.5" />
                      </button>
                    </Tooltip>
                  </div>
                </TableCell>
                <TableCell className="text-center">
                  <Badge tone="brand">{TYPE_LABEL[rule.rule_type]}</Badge>
                </TableCell>
                <TableCell className="text-center text-[--color-text-2]">
                  {rule.transaction_type}
                  {rule.count_threshold ? ` × ${rule.count_threshold}` : ""}
                </TableCell>
                <TableCell className="text-center">
                  <span className="font-mono text-[12px]">
                    {formatAmount(rule.reward_value, {
                      fractionDigits: rule.reward_type === "points" ? 0 : 2,
                    })}{" "}
                    {rule.reward_type}
                  </span>
                </TableCell>
                <TableCell className="text-center">
                  <Tooltip
                    content={perf ? describeBudgetScope(perf.budget_scope) : "—"}
                  >
                    <span>
                      <Badge tone={budget.tone}>{budget.label}</Badge>
                    </span>
                  </Tooltip>
                </TableCell>
                <TableCell className="text-center font-mono tabular-nums text-[12px]">
                  {perf ? perf.total_fires.toLocaleString() : "—"}
                </TableCell>
                <TableCell className="text-center font-mono tabular-nums text-[12px]">
                  {perf ? perf.unique_users_rewarded.toLocaleString() : "—"}
                </TableCell>
                <TableCell className="text-center">
                  <StatusPill
                    status={rule.status.toUpperCase()}
                    variant="dense"
                  />
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-center gap-0.5">
                    <Tooltip content="View details">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="View campaign"
                        onClick={() =>
                          setActive({ rule, performance: perf ?? null, action: "view" })
                        }
                      >
                        <Eye className="h-3.5 w-3.5" />
                      </Button>
                    </Tooltip>
                    <Tooltip content="Edit campaign">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Edit campaign"
                        onClick={() =>
                          setActive({ rule, performance: perf ?? null, action: "edit" })
                        }
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                    </Tooltip>
                    <Tooltip content="Deactivate campaign">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Deactivate campaign"
                        onClick={() =>
                          setActive({ rule, performance: perf ?? null, action: "delete" })
                        }
                      >
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      </Button>
                    </Tooltip>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      {active && (
        <>
          <CampaignDetailDrawer
            rule={active.rule}
            performance={active.performance}
            segments={segments}
            segmentGroups={segmentGroups}
            open={active.action === "view"}
            onOpenChange={(o) => (o ? null : close())}
          />
          <EditCampaignDialog
            rule={active.rule}
            tenantId={tenantId}
            segments={segments}
            segmentGroups={segmentGroups}
            open={active.action === "edit"}
            onOpenChange={(o) => (o ? null : close())}
          />
          <DeleteCampaignDialog
            rule={active.rule}
            tenantId={tenantId}
            open={active.action === "delete"}
            onOpenChange={(o) => (o ? null : close())}
          />
        </>
      )}
    </div>
  );
}
