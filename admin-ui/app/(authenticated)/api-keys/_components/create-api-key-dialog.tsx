"use client";

import { Check, Copy } from "lucide-react";
import * as React from "react";

import { createApiKeyAction } from "@/app/(authenticated)/api-keys/_actions";
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
import type { ApiKeyCreated } from "@/lib/api-types";

export function CreateApiKeyDialog({
  tenantId,
  trigger,
}: {
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [label, setLabel] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [created, setCreated] = React.useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = React.useState(false);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setLabel("");
      setError(null);
      setCreated(null);
      setCopied(false);
      setSubmitting(false);
    }
  }, [open]);

  const onSubmit = async () => {
    setError(null);
    setSubmitting(true);
    const result = await createApiKeyAction({
      tenant_id: tenantId,
      label: label.trim() || undefined,
    });
    setSubmitting(false);
    if (!result.ok) {
      setError(`${result.errorCode}: ${result.message}`);
      return;
    }
    setCreated(result.key);
    toast({ title: "API key created", description: result.key.key_id });
  };

  const copySecret = async () => {
    if (!created) return;
    await navigator.clipboard.writeText(created.secret);
    setCopied(true);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{created ? "Copy your API secret now" : "New API key"}</DialogTitle>
          <DialogDescription>
            {created
              ? "This secret is shown once and cannot be retrieved again. Store it somewhere safe before closing."
              : "Mint a key a partner can use to call the external user-creation API for this tenant."}
          </DialogDescription>
        </DialogHeader>

        {!created ? (
          <div className="space-y-4">
            <div>
              <Label htmlFor="label">Label (optional)</Label>
              <Input
                id="label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="partner-acme"
              />
            </div>
            {error && <ErrorBanner title="Couldn't create" description={error} />}
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <Label>Key ID</Label>
              <div className="rounded-md border bg-muted/30 px-3 py-2 font-mono text-xs">
                {created.key_id}
              </div>
            </div>
            <div>
              <Label>Secret</Label>
              <div className="flex items-center gap-2">
                <div className="flex-1 break-all rounded-md border bg-muted/30 px-3 py-2 font-mono text-xs">
                  {created.secret}
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Copy secret"
                  onClick={copySecret}
                >
                  {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                </Button>
              </div>
            </div>
          </div>
        )}

        <DialogFooter>
          {!created ? (
            <>
              <Button variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
                Cancel
              </Button>
              <Button onClick={onSubmit} disabled={submitting}>
                {submitting ? "Creating…" : "Create"}
              </Button>
            </>
          ) : (
            <Button onClick={() => setOpen(false)}>Done</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
