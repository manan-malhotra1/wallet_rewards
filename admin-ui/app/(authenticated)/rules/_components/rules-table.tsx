/**
 * <RulesTable> — dense table of every rule in the active tenant.
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

import type { Rule } from "@/lib/api-types";
import { formatAmount, shortId } from "@/lib/utils";

export function RulesTable({ rules }: { rules: Rule[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface-1]">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Name</TableHeaderCell>
            <TableHeaderCell>Type</TableHeaderCell>
            <TableHeaderCell>Trigger</TableHeaderCell>
            <TableHeaderCell>Reward</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell className="text-right">Rule ID</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rules.map((rule) => (
            <TableRow key={rule.id}>
              <TableCell className="font-medium">{rule.name}</TableCell>
              <TableCell>
                <Badge tone="brand">{rule.rule_type}</Badge>
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
              <TableCell>
                <StatusPill status={rule.status.toUpperCase()} variant="dense" />
              </TableCell>
              <TableCell className="text-right font-mono text-[11px] text-[--color-text-3]">
                {shortId(rule.id, "rule")}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
