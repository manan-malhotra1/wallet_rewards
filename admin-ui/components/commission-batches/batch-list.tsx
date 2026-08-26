"use client";

/**
 * The batch list for one menu — headers only, newest first.
 *
 * Rows link to the detail screen where the checker sees the per-row delta.
 */
import Link from "next/link";

import type { CommissionBatch } from "@/lib/api-types";
import { batchStatusLabel } from "@/lib/commission-batch";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";

/** Badge tone per batch status — a partial apply must not read as success. */
function statusVariant(
  status: string,
): "success" | "warning" | "destructive" | "secondary" {
  if (status === "APPLIED") return "success";
  if (status === "APPLIED_PARTIAL") return "warning";
  if (status === "REJECTED" || status === "WITHDRAWN") return "destructive";
  return "secondary";
}

export function BatchList({
  batches,
  basePath,
}: {
  batches: CommissionBatch[];
  basePath: string;
}) {
  return (
    <Table>
      <TableHead>
        <TableRow>
          <TableHeaderCell>File</TableHeaderCell>
          <TableHeaderCell className="text-right">Rows</TableHeaderCell>
          <TableHeaderCell className="text-right">Total</TableHeaderCell>
          <TableHeaderCell>Status</TableHeaderCell>
          <TableHeaderCell>Uploaded</TableHeaderCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {batches.map((batch) => (
          <TableRow key={batch.id} data-testid="batch-list-row">
            <TableCell>
              <Link
                href={`${basePath}/${batch.id}`}
                className="font-medium underline-offset-4 hover:underline"
              >
                {batch.file_name}
              </Link>
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {batch.row_count_valid}/{batch.row_count_total}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {batch.amount_total}
            </TableCell>
            <TableCell>
              <Badge variant={statusVariant(batch.status)}>
                {batchStatusLabel(batch.status)}
              </Badge>
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">
              {new Date(batch.created_at).toLocaleString()}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
