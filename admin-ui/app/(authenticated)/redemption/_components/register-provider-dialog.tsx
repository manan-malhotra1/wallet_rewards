/**
 * <RegisterProviderDialog> — admin form to register a redemption provider.
 *
 * Includes the optional `shared_secret` field that Phase F.5 added — when
 * set, providers can call back via `/redemption/{id}/callback` with an
 * HMAC-signed body to auto-finalise redemptions.
 */
"use client";

import * as React from "react";

import { registerProviderAction } from "@/app/(authenticated)/redemption/_actions";
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
  status_check_url: string;
  max_retries: string;
  retry_interval_secs: string;
  escalate_after_mins: string;
  shared_secret: string;
}

const INITIAL: FormState = {
  name: "",
  status_check_url: "",
  max_retries: "3",
  retry_interval_secs: "300",
  escalate_after_mins: "60",
  shared_secret: "",
};

export function RegisterProviderDialog({
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
    if (!form.name) {
      setErrorBanner("Provider name is required.");
      return;
    }
    if (form.shared_secret && form.shared_secret.length < 32) {
      setErrorBanner("Shared secret must be at least 32 characters.");
      return;
    }
    setSubmitting(true);
    const result = await registerProviderAction({
      tenant_id: tenantId,
      name: form.name,
      status_check_url: form.status_check_url || undefined,
      max_retries: Number(form.max_retries) || 3,
      retry_interval_secs: Number(form.retry_interval_secs) || 300,
      escalate_after_mins: Number(form.escalate_after_mins) || 60,
      shared_secret: form.shared_secret || undefined,
    });
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: "Provider registered",
      description: form.name,
    });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Register redemption provider</DialogTitle>
          <DialogDescription>
            Sets up the provider record + the system-owned points wallet
            that receives redemption credits.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              value={form.name}
              onChange={(e) => update("name", e.target.value)}
              placeholder="Mukuru Voucher"
            />
          </div>
          <div>
            <Label htmlFor="status-url">Status check URL (optional)</Label>
            <Input
              id="status-url"
              value={form.status_check_url}
              onChange={(e) => update("status_check_url", e.target.value)}
              placeholder="https://provider.example/status"
            />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor="max-retries">Max retries</Label>
              <Input
                id="max-retries"
                type="number"
                value={form.max_retries}
                onChange={(e) => update("max_retries", e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="retry-interval">Retry interval (s)</Label>
              <Input
                id="retry-interval"
                type="number"
                value={form.retry_interval_secs}
                onChange={(e) => update("retry_interval_secs", e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="escalate-after">Escalate after (min)</Label>
              <Input
                id="escalate-after"
                type="number"
                value={form.escalate_after_mins}
                onChange={(e) => update("escalate_after_mins", e.target.value)}
              />
            </div>
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
              placeholder="Paste the provider's webhook signing key"
              autoComplete="new-password"
            />
            <p className="mt-1 text-[11px] text-[--color-text-3]">
              When set, the provider can finalise redemptions via{" "}
              <code>POST /redemption/&#123;id&#125;/callback</code> with an
              HMAC-signed body. Phase F.5.
            </p>
          </div>
          {errorBanner && <ErrorBanner title="Couldn't register" description={errorBanner} />}
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
