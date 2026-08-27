/**
 * <UserReportsPanel> — the users who report to this one.
 *
 * The hierarchy used to be readable only upwards: a user knew their
 * supervisor, but a supervisor could not see who fed them. That gap matters
 * more since parent commission started paying supervisors off the same link —
 * an operator reconciling a commission run needs to know which users feed it,
 * which is why each row carries the child's accrued commission rather than
 * stopping at their name.
 */
import Link from "next/link";

import type { UserReport } from "@/lib/api-endpoints";

import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";

/** Render the accrued balances as "ZAR 10.00 · INR 0.00", or an em dash. */
function accruedLabel(accrued: Record<string, string>): string {
  const parts = Object.entries(accrued)
    .filter(([, value]) => Number(value) !== 0)
    .map(([currency, value]) => `${currency} ${Number(value).toFixed(2)}`);
  return parts.length > 0 ? parts.join(" · ") : "—";
}

export function UserReportsPanel({
  reports,
  total,
}: {
  reports: UserReport[];
  total: number;
}) {
  if (reports.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Nobody reports to this user yet.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {total} user{total === 1 ? "" : "s"} report to this one. Their accrued
        commission is what each has earned but not yet had disbursed.
      </p>
      <div className="-mx-5 overflow-x-auto">
        <Table>
          <TableHead>
            <TableRow>
              <TableHeaderCell>Name</TableHeaderCell>
              <TableHeaderCell>Type</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              <TableHeaderCell className="text-right">
                Accrued commission
              </TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {reports.map((r) => (
              <TableRow key={r.id}>
                <TableCell>
                  <Link
                    href={`/users?user_id=${r.id}`}
                    className="font-medium underline-offset-4 hover:underline"
                  >
                    {r.name ?? "Unnamed user"}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {r.user_type}
                </TableCell>
                <TableCell>
                  <StatusPill status={r.status.toUpperCase()} variant="dense" />
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {accruedLabel(r.accrued_commission)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
