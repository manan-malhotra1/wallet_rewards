/**
 * <CreateInstrumentDialog> — admin form to add a new instrument to the
 * tenant catalog.
 *
 * The "Create accounts for existing users" checkbox triggers a one-shot
 * backfill on the backend: every current user in the tenant gets an
 * account in this instrument so the wallet is immediately usable. Off
 * by default — new instruments typically debut for future signups.
 */
"use client";

import * as React from "react";

import { createInstrumentAction } from "@/app/(authenticated)/instruments/_actions";
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

const CODE_PATTERN = /^[A-Z][A-Z0-9_]*$/;
type AccountType = "financial_wallet" | "points_account";

export function CreateInstrumentDialog({
  tenantId,
  trigger,
}: {
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [code, setCode] = React.useState("");
  const [symbol, setSymbol] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [accountType, setAccountType] = React.useState<AccountType>(
    "financial_wallet",
  );
  const [assignToExisting, setAssignToExisting] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setCode("");
      setSymbol("");
      setDisplayName("");
      setDescription("");
      setAccountType("financial_wallet");
      setAssignToExisting(false);
      setError(null);
    }
  }, [open]);

  async function onSubmit() {
    setError(null);
    if (!CODE_PATTERN.test(code)) {
      setError(
        "Code must be uppercase letters, digits, and underscores; start with a letter.",
      );
      return;
    }
    if (code.length > 10) {
      setError("Code must be 10 characters or fewer.");
      return;
    }
    if (!symbol.trim() || !displayName.trim()) {
      setError("Symbol and display name are required.");
      return;
    }
    setSubmitting(true);
    const res = await createInstrumentAction({
      tenant_id: tenantId,
      code,
      symbol: symbol.trim(),
      display_name: displayName.trim(),
      description: description.trim() || undefined,
      account_type: accountType,
      assign_to_existing_users: assignToExisting,
    });
    setSubmitting(false);
    if (res.ok) {
      toast({
        title: "Instrument created",
        description: assignToExisting
          ? `${displayName} — accounts backfilled for existing users.`
          : displayName,
      });
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
          <DialogTitle>New instrument</DialogTitle>
          <DialogDescription>
            A value unit (currency or points). The code is referenced in
            every ledger row and cannot be changed after creation.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="inst-code">Code</Label>
              <Input
                id="inst-code"
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                placeholder="USDC"
                maxLength={10}
                className="mt-1 font-mono text-[12px]"
              />
              <p className="mt-1 text-[11px] text-[--color-text-3]">Up to 10 chars.</p>
            </div>
            <div>
              <Label htmlFor="inst-symbol">Symbol</Label>
              <Input
                id="inst-symbol"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                placeholder="$"
                maxLength={10}
                className="mt-1"
              />
            </div>
          </div>
          <div>
            <Label htmlFor="inst-name">Display name</Label>
            <Input
              id="inst-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="USD Coin"
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="inst-desc">Description (optional)</Label>
            <Input
              id="inst-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label>Account type</Label>
            <Select
              value={accountType}
              onValueChange={(v) => setAccountType(v as AccountType)}
            >
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="financial_wallet">Financial wallet (fiat)</SelectItem>
                <SelectItem value="points_account">Points account (loyalty)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-[--color-border] bg-[--color-surface-2] p-3">
            <input
              type="checkbox"
              checked={assignToExisting}
              onChange={(e) => setAssignToExisting(e.target.checked)}
              className="mt-0.5"
            />
            <span className="text-[12px]">
              <span className="font-medium">Create accounts for existing users.</span>
              <span className="block text-[11px] text-[--color-text-3]">
                Backfills one account per current tenant user. Without this, only future signups get the new wallet automatically.
              </span>
            </span>
          </label>
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
