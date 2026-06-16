/**
 * <RegisterEventSourceDialog> — admin form for `POST /events/sources`.
 *
 * Same shape as the provider register dialog; the `shared_secret` field
 * is what makes Phase F.5 HMAC enforcement actually trigger for inbound
 * events from this source.
 */
"use client";

import * as React from "react";

import { registerEventSourceAction } from "@/app/(authenticated)/events/_actions";
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

interface FormState {
  name: string;
  source_key: string;
  field_mapping: string;
  shared_secret: string;
}

const INITIAL: FormState = {
  name: "",
  source_key: "",
  field_mapping: "",
  shared_secret: "",
};

export function RegisterEventSourceDialog({
  tenantId,
  trigger,
}: {
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(INITIAL);
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm(INITIAL);
      setErrorBanner(null);
    }
  }, [open]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async () => {
    setErrorBanner(null);
    if (!form.name || !form.source_key) {
      setErrorBanner("Name and source_key are required.");
      return;
    }
    let mapping: Record<string, unknown> | undefined;
    if (form.field_mapping.trim()) {
      try {
        mapping = JSON.parse(form.field_mapping);
      } catch {
        setErrorBanner("Field mapping must be valid JSON.");
        return;
      }
    }
    if (form.shared_secret && form.shared_secret.length < 32) {
      setErrorBanner("Shared secret must be at least 32 characters.");
      return;
    }
    setSubmitting(true);
    const result = await registerEventSourceAction({
      tenant_id: tenantId,
      name: form.name,
      source_key: form.source_key,
      field_mapping: mapping,
      shared_secret: form.shared_secret || undefined,
    });
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({ title: "Source registered", description: form.name });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Register event source</DialogTitle>
          <DialogDescription>
            External systems that publish reward-triggering events must be
            registered before their events are accepted (Pay-PRD-0495).
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              placeholder="Sasai Bill Pay"
            />
          </div>
          <div>
            <Label htmlFor="source-key">Source key (globally unique)</Label>
            <Input
              id="source-key"
              value={form.source_key}
              onChange={(e) => update("source_key", e.target.value)}
              placeholder="sasai-bill-pay-za"
            />
          </div>
          <div>
            <Label htmlFor="field-mapping">Field mapping (JSON, optional)</Label>
            <textarea
              id="field-mapping"
              value={form.field_mapping}
              onChange={(e) => update("field_mapping", e.target.value)}
              rows={4}
              placeholder='{"merchant": "merchant_id"}'
              className="mt-1 w-full rounded-md border border-[--color-border] bg-[--color-surface-1] px-2.5 py-2 text-[12px] font-mono text-[--color-text-1] placeholder:text-[--color-text-3] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[--color-brand]"
            />
          </div>
          <div>
            <Label htmlFor="shared-secret">
              HMAC shared secret (optional, ≥ 32 chars)
            </Label>
            <Input
              id="shared-secret"
              type="password"
              value={form.shared_secret}
              onChange={(e) => update("shared_secret", e.target.value)}
              placeholder="Paste the source's webhook signing key"
              autoComplete="new-password"
            />
            <p className="mt-1 text-[11px] text-[--color-text-3]">
              When set, every inbound event from this source must carry
              an HMAC-SHA256 signature (Phase F.5).
            </p>
          </div>
          {errorBanner && <ErrorBanner title="Couldn't register source" description={errorBanner} />}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Saving…" : "Register"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
