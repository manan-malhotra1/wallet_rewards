/**
 * <AddIdentifierDialog> — admin affordance to add an identifier to an existing
 * user (Epic 27, Story 27.2).
 *
 * A small dialog with an identifier-type select (Phone / Email / Account number
 * — never card) plus a value input, calling `addIdentifierAction`. Admin-added
 * identifiers land unverified. On success it toasts and refreshes so the new
 * row appears in the Identifiers list; errors show inline.
 */
"use client";

import { Plus } from "lucide-react";
import * as React from "react";
import { useRouter } from "next/navigation";

import { addIdentifierAction } from "@/app/(authenticated)/users/_actions";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
import type { AddableIdentifierType } from "@/lib/api-types";

/** The three addable identifier types + their labels (no card_number). */
const TYPE_OPTIONS: { value: AddableIdentifierType; label: string }[] = [
  { value: "phone", label: "Phone" },
  { value: "email", label: "Email" },
  { value: "account_number", label: "Account number" },
];

/** Per-type placeholder shown in the value input. */
const PLACEHOLDER: Record<AddableIdentifierType, string> = {
  phone: "+27 82 555 0142",
  email: "jane@example.com",
  account_number: "ZA-001-887-2210",
};

export function AddIdentifierDialog({
  userId,
  tenantId,
}: {
  userId: string;
  tenantId: string;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [open, setOpen] = React.useState(false);
  const [type, setType] = React.useState<AddableIdentifierType>("phone");
  const [value, setValue] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Reset transient state when the dialog closes.
  React.useEffect(() => {
    if (!open) {
      setType("phone");
      setValue("");
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  const onSubmit = async () => {
    setError(null);
    const trimmed = value.trim();
    if (!trimmed) {
      setError("Enter an identifier value.");
      return;
    }
    setSubmitting(true);
    const result = await addIdentifierAction(userId, tenantId, {
      identifier_type: type,
      identifier_value: trimmed,
    });
    setSubmitting(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    toast({ title: "Identifier added" });
    setOpen(false);
    // Reflect the new (unverified) row in the server-rendered detail card.
    router.refresh();
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        className="gap-1.5"
      >
        <Plus className="h-3.5 w-3.5" />
        Add identifier
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Add identifier</DialogTitle>
            <DialogDescription>
              Attach a phone, email, or account number to this user. Admin-added
              identifiers are stored unverified.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <Label htmlFor="add-idtype">Type</Label>
                <Select
                  value={type}
                  onValueChange={(v) => setType(v as AddableIdentifierType)}
                >
                  <SelectTrigger id="add-idtype">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TYPE_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="col-span-2">
                <Label htmlFor="add-idvalue">Value</Label>
                <Input
                  id="add-idvalue"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder={PLACEHOLDER[type]}
                />
              </div>
            </div>
            <div className="space-y-1 text-[11px] text-muted-foreground">
              <p>
                Account numbers are added unverified and require a separate
                verification step.
              </p>
              <p>Card numbers are added via tokenisation (coming soon).</p>
            </div>
            {error && <ErrorBanner title="Could not add" description={error} />}
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setOpen(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button onClick={onSubmit} disabled={submitting}>
              {submitting ? "Adding…" : "Add identifier"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
