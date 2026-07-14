/**
 * Reconciliation page — operator's daily-driver. Pending and manual-review
 * queues with an inline sweep trigger.
 */
import { RefreshCcw, ScanLine } from "lucide-react";

import { getActiveTenantId } from "@/lib/active-tenant";
import { listManualReview, listPendingRedemptions } from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatAmount, shortId } from "@/lib/utils";

import { SweepButton } from "./_components/sweep-button";

export const dynamic = "force-dynamic";

export default async function ReconciliationPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="px-6 py-8">
        <EmptyState
          icon={ScanLine}
          title="No active tenant"
          description="Switch to a tenant to view its reconciliation queue."
        />
      </div>
    );
  }

  const [pendingResult, manualResult] = await Promise.allSettled([
    listPendingRedemptions(activeTenantId, 5),
    listManualReview(activeTenantId),
  ]);

  const pending = pendingResult.status === "fulfilled" ? pendingResult.value : [];
  const manualReview = manualResult.status === "fulfilled" ? manualResult.value : [];
  const error =
    pendingResult.status === "rejected" && pendingResult.reason instanceof ApiError
      ? pendingResult.reason
      : null;

  return (
    <div>
      <PageHeader
        title="Reconciliation"
        subtitle="Stale PENDING redemptions get re-checked; max-retries escalates to manual review."
        actions={<SweepButton tenantId={activeTenantId} />}
      />
      <div className="px-6 py-6">
        {error && (
          <ErrorBanner
            className="mb-4"
            title="Couldn't load queue"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        <Tabs defaultValue="pending">
          <TabsList>
            <TabsTrigger value="pending">Pending ({pending.length})</TabsTrigger>
            <TabsTrigger value="manual">Manual review ({manualReview.length})</TabsTrigger>
          </TabsList>
          <TabsContent value="pending">
            {pending.length === 0 ? (
              <EmptyState
                icon={RefreshCcw}
                title="Nothing pending"
                description="All PENDING redemptions are within the 5-minute threshold."
              />
            ) : (
              <div className="overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface-1]">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableHeaderCell>Redemption</TableHeaderCell>
                      <TableHeaderCell>Amount</TableHeaderCell>
                      <TableHeaderCell>Age</TableHeaderCell>
                      <TableHeaderCell>Retries</TableHeaderCell>
                      <TableHeaderCell>Status</TableHeaderCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {pending.map((item) => (
                      <TableRow key={item.redemption_id}>
                        <TableCell className="font-mono text-[12px]">
                          {shortId(item.redemption_id, "red")}
                        </TableCell>
                        <TableCell className="font-mono">
                          {formatAmount(item.amount, { fractionDigits: 0 })} pts
                        </TableCell>
                        <TableCell className="text-[--color-text-2]">
                          {item.age_minutes}m
                        </TableCell>
                        <TableCell className="text-[--color-text-2]">
                          {item.retry_count}
                        </TableCell>
                        <TableCell>
                          <StatusPill status="PENDING" variant="dense" />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </TabsContent>
          <TabsContent value="manual">
            {manualReview.length === 0 ? (
              <EmptyState
                icon={RefreshCcw}
                title="No manual review items"
                description="When a redemption exceeds its provider's max_retries, the sweep parks it here for operator review."
              />
            ) : (
              <div className="overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface-1]">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableHeaderCell>Redemption</TableHeaderCell>
                      <TableHeaderCell>User</TableHeaderCell>
                      <TableHeaderCell>Amount</TableHeaderCell>
                      <TableHeaderCell>Retries</TableHeaderCell>
                      <TableHeaderCell>Failure reason</TableHeaderCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {manualReview.map((item) => (
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
                        <TableCell className="text-[--color-text-2]">
                          {item.retry_count}
                        </TableCell>
                        <TableCell className="text-[--color-text-2]">
                          {item.failure_reason ?? "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
