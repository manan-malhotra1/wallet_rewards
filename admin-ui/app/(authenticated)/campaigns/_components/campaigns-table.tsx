/**
 * <CampaignsTable> — dense table of every campaign (rule) in the active
 * tenant. Each row shows campaign performance: total fires + unique
 * users rewarded, sourced from the live /performance endpoint.
 *
 * Failures to load a row's performance render as em-dashes (no crash).
 */
import { Badge } from "@/components/ui/badge";
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";

import type { Rule, RulePerformance } from "@/lib/api-types";
import { formatAmount, shortId } from "@/lib/utils";

/**
 * Map the backend's rule_type enum to operator-friendly labels.
 *
 * "campaign" is the time-boxed sub-type — relabel as "Time-boxed" so it
 * doesn't collide with the parent "Campaign" concept that names this
 * whole page.
 */
const TYPE_LABEL: Record<Rule["rule_type"], string> = {
  milestone: "Milestone",
  streak: "Streak",
  first_time: "First-time",
  value_based: "Value-based",
  composite: "Composite",
  campaign: "Time-boxed",
  referral: "Referral",
};

export function CampaignsTable({
  rules,
  performance,
}: {
  rules: Rule[];
  performance: Record<string, RulePerformance | null>;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface-1]">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Name</TableHeaderCell>
            <TableHeaderCell>Type</TableHeaderCell>
            <TableHeaderCell>Trigger</TableHeaderCell>
            <TableHeaderCell>Reward</TableHeaderCell>
            <TableHeaderCell className="text-right">Fires</TableHeaderCell>
            <TableHeaderCell className="text-right">Unique users</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell className="text-right">Campaign ID</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rules.map((rule) => {
            const perf = performance[rule.id];
            return (
              <TableRow key={rule.id}>
                <TableCell className="font-medium">{rule.name}</TableCell>
                <TableCell>
                  <Badge tone="brand">{TYPE_LABEL[rule.rule_type]}</Badge>
                </TableCell>
                <TableCell className="text-[--color-text-2]">
                  {rule.transaction_type}
                  {rule.count_threshold ? ` × ${rule.count_threshold}` : ""}
                </TableCell>
                <TableCell>
                  <span className="font-mono text-[12px]">
                    {formatAmount(rule.reward_value, {
                      fractionDigits: rule.reward_type === "points" ? 0 : 2,
                    })}{" "}
                    {rule.reward_type}
                  </span>
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums text-[12px]">
                  {perf ? perf.total_fires.toLocaleString() : "—"}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums text-[12px]">
                  {perf ? perf.unique_users_rewarded.toLocaleString() : "—"}
                </TableCell>
                <TableCell>
                  <StatusPill
                    status={rule.status.toUpperCase()}
                    variant="dense"
                  />
                </TableCell>
                <TableCell className="text-right font-mono text-[11px] text-[--color-text-3]">
                  {shortId(rule.id, "campaign")}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
