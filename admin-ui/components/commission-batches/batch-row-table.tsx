"use client";

/**
 * The checker's row table for a commission batch.
 *
 * The DELTA column is the reason this screen exists (spec §8.3): it makes
 * "accrued R1,620, paying R1,500" visible at a glance, with the maker's note
 * supplying the why. A non-zero delta is rendered prominently — it is the
 * signal the checker is here to evaluate, not an incidental column.
 */
import type { CommissionBatchRow } from "@/lib/api-types";
import {
  rejectReasonLabel,
  rowDelta,
  rowStatusLabel,
} from "@/lib/commission-batch";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";

/** Format a decimal string for display, or an em dash when absent. */
function money(value: string | null | undefined): string {
  if (value == null) return "—";
  const n = Number(value);
  return Number.isNaN(n) ? value : n.toFixed(2);
}

/** Badge tone per row status — failures must not read as success. */
function statusVariant(status: string): "success" | "destructive" | "secondary" {
  if (status === "posted") return "success";
  if (status === "rejected" || status === "failed") return "destructive";
  return "secondary";
}

export function BatchRowTable({ rows }: { rows: CommissionBatchRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground py-6 text-center text-sm">
        This batch has no rows.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell className="w-12">#</TableHeaderCell>
            <TableHeaderCell>Mobile number</TableHeaderCell>
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell className="text-right">Accrued</TableHeaderCell>
            <TableHeaderCell className="text-right">Paying</TableHeaderCell>
            <TableHeaderCell className="text-right">Delta</TableHeaderCell>
            <TableHeaderCell>Note</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => {
            const delta = rowDelta(row.balance_snapshot, row.amount);
            const held = delta != null && delta > 0;
            return (
              <TableRow key={row.id} data-testid={`batch-row-${row.row_number}`}>
                <TableCell className="text-muted-foreground">
                  {row.row_number}
                </TableCell>
                <TableCell className="font-mono text-xs">{row.msisdn}</TableCell>
                <TableCell>{row.currency}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {money(row.balance_snapshot)}
                </TableCell>
                <TableCell className="text-right font-semibold tabular-nums">
                  {money(row.amount)}
                </TableCell>
                <TableCell
                  className={
                    held
                      ? "text-right font-semibold tabular-nums text-amber-600"
                      : "text-muted-foreground text-right tabular-nums"
                  }
                  data-testid={`batch-delta-${row.row_number}`}
                >
                  {delta == null ? "—" : delta.toFixed(2)}
                </TableCell>
                <TableCell className="max-w-[22rem] text-sm">
                  {row.note ?? (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={statusVariant(row.status)}>
                    {rowStatusLabel(row.status)}
                  </Badge>
                  {row.failure_reason ? (
                    <p className="text-muted-foreground mt-1 text-xs">
                      {rejectReasonLabel(row.failure_reason)}
                    </p>
                  ) : null}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
