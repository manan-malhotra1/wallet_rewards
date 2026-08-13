/**
 * Operations "needs attention" strip — pending reconciliation and manual
 * review counts for the active tenant. Server component; links out to the
 * relevant queues. Retains the ops-cockpit value of the old dashboard.
 */
import { AlertTriangle, ScanLine } from "lucide-react";
import Link from "next/link";

import { listManualReview, listPendingRedemptions } from "@/lib/api-endpoints";

export async function AttentionStrip({ tenantId }: { tenantId: string }) {
  const [pending, manual] = await Promise.all([
    listPendingRedemptions(tenantId, 5).catch(() => []),
    listManualReview(tenantId).catch(() => []),
  ]);
  if (pending.length === 0 && manual.length === 0) return null;

  return (
    <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
      <Link href="/reconciliation" className="glass-panel flex items-center gap-3 rounded-lg p-4 hover:border-primary/40">
        <ScanLine className="h-5 w-5 text-amber-500" aria-hidden="true" />
        <div>
          <div className="text-lg font-bold tabular-nums">{pending.length}</div>
          <div className="text-xs text-muted-foreground">Pending reconciliation</div>
        </div>
      </Link>
      <Link href="/reconciliation" className="glass-panel flex items-center gap-3 rounded-lg p-4 hover:border-primary/40">
        <AlertTriangle className="h-5 w-5 text-red-500" aria-hidden="true" />
        <div>
          <div className="text-lg font-bold tabular-nums">{manual.length}</div>
          <div className="text-xs text-muted-foreground">Manual review</div>
        </div>
      </Link>
    </div>
  );
}
