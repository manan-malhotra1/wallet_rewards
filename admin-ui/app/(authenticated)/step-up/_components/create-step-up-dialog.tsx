/**
 * <CreateStepUpDialog> — admin form for POST /step-up/policies.
 *
 * Single threshold field: transactions above this value require the
 * user to re-enter their PIN.
 */
"use client";

import * as React from "react";

import { createStepUpPolicyAction } from "@/app/(authenticated)/step-up/_actions";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";

type TxnType = "p2p" | "redemption";

interface FormState {
  transaction_type: TxnType;
  currency: string;
  threshold_amount: string;
}

const INITIAL: FormState = {
  transaction_type: "p2p",
  currency: "ZAR",
  threshold_amount: "200",
};

export function CreateStepUpDialog({
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
    const n = Number(form.threshold_amount);
    if (!Number.isFinite(n) || n < 0) {
      setErrorBanner("Threshold must be a non-negative number.");
      return;
    }
    setSubmitting(true);
    const result = await createStepUpPolicyAction({
      tenant_id: tenantId,
      transaction_type: form.transaction_type,
      currency: form.currency.toUpperCase(),
      threshold_amount: form.threshold_amount,
    });
    setSubmitting(false);
    if (result.ok) {
      toast({ title: "Policy created" });
      setOpen(false);
    } else {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
    }
  };

  // Currency defaults sensibly per txn type — redemption is always points.
  React.useEffect(() => {
    if (form.transaction_type === "redemption" && form.currency !== "PTS") {
      update("currency", "PTS");
    }
    if (form.transaction_type === "p2p" && form.currency === "PTS") {
      update("currency", "ZAR");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.transaction_type]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New step-up policy</DialogTitle>
          <DialogDescription>
            Transactions exceeding the threshold below will require the user
            to re-enter their PIN before processing.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label>Transaction type</Label>
            <Select
              value={form.transaction_type}
              onValueChange={(v) => update("transaction_type", v as TxnType)}
            >
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="p2p">Peer-to-peer (money)</SelectItem>
                <SelectItem value="redemption">Redemption (points)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="currency">Currency</Label>
              <Input
                id="currency"
                value={form.currency}
                onChange={(e) => update("currency", e.target.value)}
                maxLength={3}
                className="mt-1 uppercase"
              />
            </div>
            <div>
              <Label htmlFor="threshold">Threshold</Label>
              <Input
                id="threshold"
                type="number"
                step="0.01"
                min="0"
                value={form.threshold_amount}
                onChange={(e) => update("threshold_amount", e.target.value)}
                className="mt-1"
              />
            </div>
          </div>
          {errorBanner && (
            <ErrorBanner title="Couldn't create" description={errorBanner} />
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Saving…" : "Create policy"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
