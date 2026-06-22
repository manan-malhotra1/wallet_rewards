/**
 * <CreateServiceDialog> — admin form to add a new service to the tenant catalog.
 *
 * Code is locked once created (it's the immutable identifier stored in
 * downstream tables) so this dialog only appears for new entries; later
 * edits use the inline row actions in <ServicesTable>.
 */
"use client";

import * as React from "react";

import { createServiceAction } from "@/app/(authenticated)/services/_actions";
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

const CODE_PATTERN = /^[a-z][a-z0-9_]*$/;

export function CreateServiceDialog({
  tenantId,
  trigger,
}: {
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [code, setCode] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setCode("");
      setDisplayName("");
      setDescription("");
      setError(null);
    }
  }, [open]);

  async function onSubmit() {
    setError(null);
    if (!CODE_PATTERN.test(code)) {
      setError("Code must be lowercase letters, numbers, and underscores; start with a letter.");
      return;
    }
    if (!displayName.trim()) {
      setError("Display name is required.");
      return;
    }
    setSubmitting(true);
    const res = await createServiceAction({
      tenant_id: tenantId,
      code,
      display_name: displayName.trim(),
      description: description.trim() || undefined,
    });
    setSubmitting(false);
    if (res.ok) {
      toast({ title: "Service created", description: displayName });
      setOpen(false);
    } else {
      setError(`${res.errorCode}: ${res.message}`);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New service</DialogTitle>
          <DialogDescription>
            A configurable transaction type. The code is the persistent
            identifier referenced in Limits, Pricing, and Campaigns. It
            cannot be changed after creation.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label htmlFor="svc-code">Code</Label>
            <Input
              id="svc-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="bill_pay"
              className="mt-1 font-mono text-[12px]"
            />
            <p className="mt-1 text-[11px] text-[--color-text-3]">
              Lowercase letters, digits, underscores. Cannot be changed later.
            </p>
          </div>
          <div>
            <Label htmlFor="svc-name">Display name</Label>
            <Input
              id="svc-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Bill Pay"
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="svc-desc">Description (optional)</Label>
            <Input
              id="svc-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Pay a registered biller."
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
