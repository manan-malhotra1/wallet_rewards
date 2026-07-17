/**
 * <CreateUserDialog> — admin "Register user" form.
 *
 * Epic 3: this no longer creates the user directly. It PROPOSES a create_user
 * operation (N-eyes maker-checker) — on submit a PENDING request is created and
 * the maker is told it's awaiting approval. Same form fields as before:
 * one identifier (email or phone), an optional profile, and a user_type.
 */
"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { proposeCreateUserAction } from "@/app/(authenticated)/users/_actions";
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
import type { UserType } from "@/lib/api-types";

import { MERCHANT_TYPES, USER_TYPE_OPTIONS } from "./user-type-badge";

interface FormState {
  identifierType: "phone" | "email";
  identifierValue: string;
  userType: UserType;
  firstName: string;
  lastName: string;
  dateOfBirth: string;
}

const EMPTY_FORM: FormState = {
  identifierType: "phone",
  identifierValue: "",
  userType: "consumer",
  firstName: "",
  lastName: "",
  dateOfBirth: "",
};

export function CreateUserDialog({
  tenantId,
  trigger,
}: {
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) {
      setForm(EMPTY_FORM);
      setErrorBanner(null);
    }
  }, [open]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const isMerchant = MERCHANT_TYPES.includes(form.userType);

  const onSubmit = async () => {
    setErrorBanner(null);
    const identifierValue = form.identifierValue.trim();
    if (!identifierValue) {
      setErrorBanner("Enter a phone number or email address.");
      return;
    }

    const str = (v: string) => (v.trim() ? v.trim() : undefined);
    const profile =
      form.firstName.trim() || form.lastName.trim() || form.dateOfBirth
        ? {
            first_name: str(form.firstName),
            last_name: str(form.lastName),
            date_of_birth: form.dateOfBirth || undefined,
          }
        : undefined;

    setSubmitting(true);
    const result = await proposeCreateUserAction({
      tenantId,
      identifiers: [
        { identifier_type: form.identifierType, identifier_value: identifierValue },
      ],
      user_type: form.userType,
      profile,
    });
    setSubmitting(false);

    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: "Create-user request submitted",
      description: "Awaiting approval — track it under User approvals.",
    });
    setOpen(false);
    // The user doesn't exist yet — send the maker to the approvals queue.
    router.push("/user-operations");
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Register user</DialogTitle>
          <DialogDescription>
            Submits a create-user request for approval — the user is created once
            a second admin (user approver) approves it.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor="idtype">Identifier</Label>
              <Select
                value={form.identifierType}
                onValueChange={(v) => update("identifierType", v as "phone" | "email")}
              >
                <SelectTrigger id="idtype">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="phone">Phone</SelectItem>
                  <SelectItem value="email">Email</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="col-span-2">
              <Label htmlFor="idvalue">
                {form.identifierType === "phone" ? "Phone number" : "Email address"}
              </Label>
              <Input
                id="idvalue"
                value={form.identifierValue}
                onChange={(e) => update("identifierValue", e.target.value)}
                placeholder={
                  form.identifierType === "phone"
                    ? "+27 82 555 0142"
                    : "jane@example.com"
                }
              />
            </div>
          </div>

          <div>
            <Label htmlFor="utype">User type</Label>
            <Select
              value={form.userType}
              onValueChange={(v) => update("userType", v as UserType)}
            >
              <SelectTrigger id="utype">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {USER_TYPE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {isMerchant && (
            <p className="text-[11px] text-muted-foreground">
              Merchant profile (business name, category, provider config) is added
              in Epic 17 — the user is created without one for now.
            </p>
          )}

          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor="fn">First name</Label>
              <Input
                id="fn"
                value={form.firstName}
                onChange={(e) => update("firstName", e.target.value)}
                placeholder="Jane"
              />
            </div>
            <div>
              <Label htmlFor="ln">Last name</Label>
              <Input
                id="ln"
                value={form.lastName}
                onChange={(e) => update("lastName", e.target.value)}
                placeholder="Mokoena"
              />
            </div>
            <div>
              <Label htmlFor="dob">Date of birth</Label>
              <Input
                id="dob"
                type="date"
                value={form.dateOfBirth}
                onChange={(e) => update("dateOfBirth", e.target.value)}
              />
            </div>
          </div>

          {errorBanner && <ErrorBanner title="Could not submit" description={errorBanner} />}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Submitting…" : "Submit for approval"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
