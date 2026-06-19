/**
 * <DeleteCampaignDialog> — confirm + soft-delete.
 *
 * Backend sets status='inactive'. Existing reward_events are kept for
 * audit; the rule stops firing immediately.
 */
"use client";

import { AlertTriangle } from "lucide-react";
import * as React from "react";

import { deleteCampaignAction } from "@/app/(authenticated)/campaigns/_actions";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ErrorBanner } from "@/components/ui/error-banner";
import { useToast } from "@/components/ui/toast";
import type { Rule } from "@/lib/api-types";

export function DeleteCampaignDialog({
  rule,
  tenantId,
  open,
  onOpenChange,
}: {
  rule: Rule;
  tenantId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  const onConfirm = async () => {
    setSubmitting(true);
    setError(null);
    const result = await deleteCampaignAction(rule.id, tenantId);
    setSubmitting(false);
    if (result.ok) {
      toast({ title: "Campaign deactivated", description: rule.name });
      onOpenChange(false);
    } else {
      setError(`${result.errorCode}: ${result.message}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            Deactivate campaign?
          </DialogTitle>
          <DialogDescription>
            <strong>{rule.name}</strong> will stop firing immediately. Past
            reward history is preserved — you can reactivate the campaign
            by editing its status if needed.
          </DialogDescription>
        </DialogHeader>
        {error && <ErrorBanner title="Couldn't deactivate" description={error} />}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={submitting}
          >
            {submitting ? "Deactivating…" : "Deactivate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
