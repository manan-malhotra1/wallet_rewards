/**
 * <RenameBankMirrorDialog> — inline rename affordance (pencil icon) for a
 * single bank-mirror row. Opens a tiny dialog with one name field.
 */
"use client";

import { Pencil } from "lucide-react";
import * as React from "react";

import { renameBankMirrorAction } from "@/app/(authenticated)/system-wallets/_actions";
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
import type { SystemWallet } from "@/lib/api-types";

export function RenameBankMirrorDialog({
  account,
  tenantId,
}: {
  account: SystemWallet;
  tenantId: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState(account.name ?? "");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setName(account.name ?? "");
      setError(null);
      setSubmitting(false);
    }
  }, [open, account.name]);

  async function onSubmit() {
    setError(null);
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    setSubmitting(true);
    const result = await renameBankMirrorAction(tenantId, account.id, name);
    setSubmitting(false);
    if (result.ok) {
      toast({ title: "Bank mirror renamed", description: result.message });
      setOpen(false);
      return;
    }
    setError(`${result.errorCode}: ${result.message}`);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          type="button"
          aria-label={`Rename ${account.name ?? "bank mirror"}`}
          className="text-[--color-text-3] hover:text-[--color-text-1]"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Rename bank mirror</DialogTitle>
          <DialogDescription>
            Give this operator_adjustment account a clear label so operators
            can pick the right counter-leg.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label htmlFor="rename-bm">Name</Label>
            <Input
              id="rename-bm"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Standard Bank — main float"
              className="mt-1"
            />
          </div>
          {error && <ErrorBanner title="Couldn't rename" description={error} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
