/**
 * <EditCampaignDialog> — patch a campaign's editable fields.
 *
 * Trigger conditions (rule_type, transaction_type, count_threshold,
 * min_amount, etc.) are intentionally read-only — they're load-bearing
 * for in-flight `user_rule_progress`. Operators wanting to change them
 * should deactivate this campaign and create a new one.
 */
"use client";

import * as React from "react";

import { updateCampaignAction } from "@/app/(authenticated)/campaigns/_actions";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import type { Rule } from "@/lib/api-types";

export function EditCampaignDialog({
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
  const [name, setName] = React.useState(rule.name);
  const [rewardValue, setRewardValue] = React.useState(String(rule.reward_value));
  const [status, setStatus] = React.useState<"active" | "inactive">(
    (rule.status as "active" | "inactive") ?? "active",
  );
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (open) {
      setName(rule.name);
      setRewardValue(String(rule.reward_value));
      setStatus((rule.status as "active" | "inactive") ?? "active");
      setError(null);
    }
  }, [open, rule]);

  const onSubmit = async () => {
    setError(null);
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    const reward = Number(rewardValue);
    if (!Number.isFinite(reward) || reward <= 0) {
      setError("Reward value must be a positive number.");
      return;
    }
    setSubmitting(true);
    const result = await updateCampaignAction(rule.id, tenantId, {
      name: name.trim(),
      reward_value: rewardValue,
      status,
    });
    setSubmitting(false);
    if (result.ok) {
      toast({ title: "Campaign updated" });
      onOpenChange(false);
    } else {
      setError(`${result.errorCode}: ${result.message}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Edit campaign</DialogTitle>
          <DialogDescription>
            Editable: name, reward value, status. Trigger conditions are
            locked once a campaign is live — deactivate this one and create
            a new one if those need to change.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label htmlFor="edit-name">Name</Label>
            <Input
              id="edit-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="edit-reward">Reward value ({rule.reward_type})</Label>
            <Input
              id="edit-reward"
              type="number"
              step="0.01"
              min="0.01"
              value={rewardValue}
              onChange={(e) => setRewardValue(e.target.value)}
              className="mt-1 tabular-nums"
            />
          </div>
          <div>
            <Label>Status</Label>
            <Select
              value={status}
              onValueChange={(v) => setStatus(v as "active" | "inactive")}
            >
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="active">Active — firing</SelectItem>
                <SelectItem value="inactive">Inactive — paused</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {error && <ErrorBanner title="Couldn't save" description={error} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Saving…" : "Save changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
