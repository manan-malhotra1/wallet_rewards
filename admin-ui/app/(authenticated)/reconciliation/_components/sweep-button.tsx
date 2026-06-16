/**
 * <SweepButton> — kicks off a reconciliation sweep for the active tenant.
 *
 * Calls the `triggerSweepAction` server action; surfaces the result in a
 * toast. Disabled while pending.
 */
"use client";

import { RefreshCcw } from "lucide-react";
import * as React from "react";

import { triggerSweepAction } from "@/app/(authenticated)/reconciliation/_actions";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

export function SweepButton({ tenantId }: { tenantId: string }) {
  const [pending, setPending] = React.useState(false);
  const { toast } = useToast();

  const onClick = async () => {
    setPending(true);
    const result = await triggerSweepAction(tenantId);
    setPending(false);
    if (!result.ok) {
      toast({
        title: "Sweep failed",
        description: `${result.errorCode}: ${result.message}`,
        variant: "danger",
      });
      return;
    }
    toast({
      title: "Sweep complete",
      description: `Scanned ${result.scanned} · bumped ${result.bumped} · escalated ${result.escalated}`,
    });
  };

  return (
    <Button onClick={onClick} disabled={pending} size="md">
      <RefreshCcw className={pending ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
      {pending ? "Sweeping…" : "Sweep now"}
    </Button>
  );
}
