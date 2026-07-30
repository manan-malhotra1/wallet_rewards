/**
 * <NewBankMirrorDialog> — creates a named bank-mirror (operator_adjustment)
 * account. Operators run several mirrors (one per real bank account); each
 * carries a human name so it can be picked as a counter-leg later.
 */
"use client";

import * as React from "react";

import { createBankMirrorAction } from "@/app/(authenticated)/system-wallets/_actions";
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

export function NewBankMirrorDialog({
  tenantId,
  currencies,
  defaultCurrency,
  trigger,
}: {
  tenantId: string;
  /** Distinct currencies present among the wallets; offered in the select. */
  currencies: string[];
  /** The active tenant's base currency — the select's preferred default. */
  defaultCurrency: string;
  trigger: React.ReactNode;
}) {
  // Offer the wallets' currencies; when none exist yet, offer the tenant's own.
  // Default to the tenant's base currency when it's on offer, else the first.
  const options = currencies.length > 0 ? currencies : [defaultCurrency];
  const initialCurrency = options.includes(defaultCurrency)
    ? defaultCurrency
    : options[0];

  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [currency, setCurrency] = React.useState(initialCurrency);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setName("");
      setCurrency(initialCurrency);
      setError(null);
      setSubmitting(false);
    }
  }, [open, initialCurrency]);

  async function onSubmit() {
    setError(null);
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    setSubmitting(true);
    const result = await createBankMirrorAction(tenantId, { name, currency });
    setSubmitting(false);
    if (result.ok) {
      toast({ title: "Proposed for approval", description: result.message });
      setOpen(false);
      return;
    }
    setError(`${result.errorCode}: ${result.message}`);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New bank mirror</DialogTitle>
          <DialogDescription>
            A named operator_adjustment account that mirrors one real bank
            account. Use it as the counter-leg for funds, withdrawals and
            float adjustments.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label htmlFor="bm-name">Name</Label>
            <Input
              id="bm-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Standard Bank — main float"
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="bm-currency">Currency</Label>
            <Select value={currency} onValueChange={setCurrency}>
              <SelectTrigger id="bm-currency" className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {options.map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {error && (
            <ErrorBanner title="Couldn't create bank mirror" description={error} />
          )}
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
