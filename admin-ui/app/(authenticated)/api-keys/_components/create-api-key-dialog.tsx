"use client";

import { Check, Copy } from "lucide-react";
import * as React from "react";

import {
  createApiKeyAction,
  resolveMerchantAction,
} from "@/app/(authenticated)/api-keys/_actions";
import { Badge } from "@/components/ui/badge";
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
import type { TreasuryIdentifierType } from "@/lib/api-endpoints";
import type { ApiKeyCreated, UserType } from "@/lib/api-types";

const IDENTIFIER_PLACEHOLDER: Record<TreasuryIdentifierType, string> = {
  phone: "+27 82 555 0001",
  email: "merchant@example.com",
  account_number: "ZA-001-887-2210",
  card_number: "5234 5678 9012 3456",
};

/** The two user types the backend accepts for a merchant-cash-in key. */
const MERCHANT_TYPES: readonly UserType[] = ["merchant", "head_merchant"];

/** A merchant confirmed by identifier lookup, ready to bind by user_id. */
interface ResolvedMerchant {
  user_id: string;
  name: string | null;
  user_type: UserType;
}

/** <CreateApiKeyDialog> — mint a partner or merchant-cash-in key for a tenant. */
export function CreateApiKeyDialog({
  tenantId,
  trigger,
}: {
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [label, setLabel] = React.useState("");
  const [identifierType, setIdentifierType] =
    React.useState<TreasuryIdentifierType>("phone");
  const [identifierValue, setIdentifierValue] = React.useState("");
  const [resolving, setResolving] = React.useState(false);
  const [resolved, setResolved] = React.useState<ResolvedMerchant | null>(null);
  const [lookupError, setLookupError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [merchantError, setMerchantError] = React.useState<string | null>(null);
  const [created, setCreated] = React.useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = React.useState(false);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setLabel("");
      setIdentifierType("phone");
      setIdentifierValue("");
      setResolving(false);
      setResolved(null);
      setLookupError(null);
      setError(null);
      setMerchantError(null);
      setCreated(null);
      setCopied(false);
      setSubmitting(false);
    }
  }, [open]);

  // Any edit to the identifier invalidates a prior lookup, so a stale name can
  // never be the one submitted.
  const clearResolution = () => {
    setResolved(null);
    setLookupError(null);
    setMerchantError(null);
  };

  const onLookup = async () => {
    if (!identifierValue.trim()) return;
    setResolving(true);
    setLookupError(null);
    setResolved(null);
    const result = await resolveMerchantAction(
      tenantId,
      identifierType,
      identifierValue.trim(),
    );
    setResolving(false);
    if (!result.ok) {
      setLookupError("No user found for that identifier.");
      return;
    }
    setResolved({
      user_id: result.user_id,
      name: result.name,
      user_type: result.user_type,
    });
  };

  const hasIdentifier = identifierValue.trim().length > 0;
  const isMerchant = resolved !== null && MERCHANT_TYPES.includes(resolved.user_type);
  // Block submit while a typed identifier is unresolved or resolves to a
  // non-merchant — we must send a validated merchant user_id, never a raw value.
  const bindingBlocked = hasIdentifier && (resolved === null || !isMerchant);

  const onSubmit = async () => {
    setError(null);
    setMerchantError(null);
    setSubmitting(true);
    const result = await createApiKeyAction({
      tenant_id: tenantId,
      label: label.trim() || undefined,
      merchant_user_id: resolved?.user_id ?? null,
    });
    setSubmitting(false);
    if (!result.ok) {
      // Defense-in-depth: the backend re-validates the bound user is a merchant.
      // Surface that inline under the merchant field, not in the generic banner.
      if (result.errorCode === "merchant_user_required") {
        setMerchantError(result.message);
        return;
      }
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
            <div>
              <Label>Merchant (enables cash-in)</Label>
              <div className="mt-1 grid grid-cols-[1fr_2fr_auto] gap-2">
                <Select
                  value={identifierType}
                  onValueChange={(v) => {
                    setIdentifierType(v as TreasuryIdentifierType);
                    clearResolution();
                  }}
                >
                  <SelectTrigger aria-label="Identifier type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="phone">Phone</SelectItem>
                    <SelectItem value="email">Email</SelectItem>
                    <SelectItem value="account_number">Account</SelectItem>
                    <SelectItem value="card_number">Card</SelectItem>
                  </SelectContent>
                </Select>
                <Input
                  value={identifierValue}
                  onChange={(e) => {
                    setIdentifierValue(e.target.value);
                    clearResolution();
                  }}
                  onBlur={() => {
                    if (hasIdentifier && !resolved && !resolving) onLookup();
                  }}
                  placeholder={IDENTIFIER_PLACEHOLDER[identifierType]}
                  aria-invalid={lookupError || merchantError ? true : undefined}
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={onLookup}
                  disabled={!hasIdentifier || resolving}
                >
                  {resolving ? "Looking up…" : "Look up"}
                </Button>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                Leave empty for a standard partner key. Set a merchant to allow this key to
                call merchant cash-in.
              </p>
              {resolved && (
                <div className="mt-2 flex items-center gap-2 text-sm">
                  {isMerchant ? (
                    <span
                      className="text-emerald-600 dark:text-emerald-400"
                      aria-hidden="true"
                    >
                      ✓
                    </span>
                  ) : null}
                  <span className="font-medium">{resolved.name ?? "Unnamed user"}</span>
                  <Badge variant={isMerchant ? "success" : "warning"}>
                    {resolved.user_type}
                  </Badge>
                </div>
              )}
              {resolved && !isMerchant && (
                <p className="mt-1 text-xs text-destructive">
                  {resolved.name ?? "This user"} is a {resolved.user_type}, not a merchant —
                  cannot bind.
                </p>
              )}
              {lookupError && (
                <p className="mt-1 text-xs text-destructive">{lookupError}</p>
              )}
              {merchantError && (
                <p className="mt-1 text-xs text-destructive">{merchantError}</p>
              )}
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
              <Button onClick={onSubmit} disabled={submitting || bindingBlocked}>
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
