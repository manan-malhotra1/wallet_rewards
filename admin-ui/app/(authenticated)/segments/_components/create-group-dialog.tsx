/**
 * <CreateGroupDialog> — form for POST /segment-groups (Segmentation Phase 1
 * Task 11).
 *
 * A segment group is the exclusive-tier "lens" segments are evaluated
 * within (e.g. "Loyalty", "Value") — within a group, only the
 * highest-priority matching segment applies to a user. This dialog only
 * creates the group shell (name + optional description); segments are
 * added to it afterwards via the "New segment" dialog's group picker.
 */
"use client";

import * as React from "react";

import { createSegmentGroupAction } from "@/app/(authenticated)/segments/_actions";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";

export function CreateGroupDialog({
  tenantId,
  trigger,
}: {
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  // Every path that closes the dialog — Radix (Esc/overlay/X), Cancel, and a
  // successful submit — routes through this one handler so the form always
  // resets, without a `useEffect` watching `open` (which would set state
  // synchronously on the render right after close, tripping
  // react-hooks/set-state-in-effect for no real benefit over doing it here).
  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setName("");
      setDescription("");
      setError(null);
    }
  };

  const onSubmit = async () => {
    setError(null);
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    setSubmitting(true);
    const res = await createSegmentGroupAction({
      tenant_id: tenantId,
      name: name.trim(),
      description: description.trim() || undefined,
    });
    setSubmitting(false);
    if (res.ok) {
      toast({ title: "Group created", description: name.trim() });
      onOpenChange(false);
    } else {
      setError(`${res.errorCode}: ${res.message}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New segment group</DialogTitle>
          <DialogDescription>
            An exclusive-tier lens — segments inside it compete on priority;
            only the top matching one applies to a given user.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label htmlFor="group-name">Name</Label>
            <Input
              id="group-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Loyalty"
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="group-desc">Description (optional)</Label>
            <Input
              id="group-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Tenure-based loyalty tiers."
              className="mt-1"
            />
          </div>
          {error && <ErrorBanner title="Couldn't create" description={error} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Creating…" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
