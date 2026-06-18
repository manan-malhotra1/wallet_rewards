/**
 * <CreateSegmentDialog> — minimal admin form for POST /segments.
 */
"use client";

import * as React from "react";

import { createSegmentAction } from "@/app/(authenticated)/segments/_actions";
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

export function CreateSegmentDialog({
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

  React.useEffect(() => {
    if (!open) {
      setName("");
      setDescription("");
      setError(null);
    }
  }, [open]);

  const onSubmit = async () => {
    setError(null);
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    setSubmitting(true);
    const res = await createSegmentAction({
      tenant_id: tenantId,
      name: name.trim(),
      description: description.trim() || undefined,
    });
    setSubmitting(false);
    if (res.ok) {
      toast({ title: "Segment created", description: name });
      setOpen(false);
    } else {
      setError(`${res.errorCode}: ${res.message}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New segment</DialogTitle>
          <DialogDescription>
            A static cohort of users. Membership is admin-assigned.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label htmlFor="seg-name">Name</Label>
            <Input
              id="seg-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="vip-users"
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="seg-desc">Description (optional)</Label>
            <Input
              id="seg-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Top 1% of customers by lifetime spend."
              className="mt-1"
            />
          </div>
          {error && <ErrorBanner title="Couldn't create" description={error} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
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
