/**
 * <ManualReviewTable> — stuck redemptions awaiting operator action.
 */
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";

import type { ManualReviewItem } from "@/lib/api-types";
import { formatAmount, shortId } from "@/lib/utils";

export function ManualReviewTable({ items }: { items: ManualReviewItem[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface-1]">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Redemption</TableHeaderCell>
            <TableHeaderCell>User</TableHeaderCell>
            <TableHeaderCell>Amount</TableHeaderCell>
            <TableHeaderCell>Retries</TableHeaderCell>
            <TableHeaderCell>Failure reason</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.redemption_id}>
              <TableCell className="font-mono text-[12px]">
                {shortId(item.redemption_id, "red")}
              </TableCell>
              <TableCell className="font-mono text-[12px]">
                {item.user_name ?? shortId(item.user_id, "usr")}
              </TableCell>
              <TableCell className="font-mono">
                {formatAmount(item.amount, { fractionDigits: 0 })} pts
              </TableCell>
              <TableCell className="text-[--color-text-2]">{item.retry_count}</TableCell>
              <TableCell className="text-[--color-text-2]">
                {item.failure_reason ?? "—"}
              </TableCell>
              <TableCell>
                <StatusPill status="MANUAL_REVIEW" variant="dense" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
