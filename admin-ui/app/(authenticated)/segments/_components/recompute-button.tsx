/**
 * <RecomputeButton> — manually enqueue a batch-evaluator recompute run for
 * every dynamic segment in the tenant (Segmentation Phase 1 Task 11).
 *
 * The evaluator also runs on a Celery beat schedule (Task 5), but an admin
 * who just edited a segment's criteria shouldn't have to wait for the next
 * tick to see `last_evaluated_at` move off "Pending recompute" — this button
 * enqueues the same async job on demand.
 */
"use client";

import { RefreshCw } from "lucide-react";
import * as React from "react";

import { recomputeSegmentsAction } from "@/app/(authenticated)/segments/_actions";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

export function RecomputeButton({ tenantId }: { tenantId: string }) {
  const [pending, setPending] = React.useState(false);
  const { toast } = useToast();

  const onClick = async () => {
    setPending(true);
    const res = await recomputeSegmentsAction(tenantId);
    setPending(false);
    if (res.ok) {
      toast({ title: "Recompute enqueued — memberships refresh shortly" });
    } else {
      toast({
        title: "Couldn't enqueue recompute",
        description: `${res.errorCode}: ${res.message}`,
        variant: "danger",
      });
    }
  };

  return (
    <Button variant="outline" onClick={onClick} disabled={pending}>
      <RefreshCw className="h-3.5 w-3.5" />
      {pending ? "Enqueuing…" : "Recompute now"}
    </Button>
  );
}
