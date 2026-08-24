/**
 * <CreateUserDialog> — admin "Register user" form.
 *
 * Epic 3: this no longer creates the user directly. It PROPOSES a create_user
 * operation (N-eyes maker-checker) — on submit a PENDING request is created and
 * the maker is told it's awaiting approval. One identifier (email or phone), an
 * optional profile, a user type, and — when that type is a child type — an
 * optional supervisor.
 *
 * The type list is the tenant's runtime catalog, not a hardcoded set, so a type
 * an operator created on /user-types is assignable here the moment it is
 * approved. Whether a supervisor block appears is read off the chosen type's
 * `parent_type_code` for the same reason.
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
import { UserTypeSelect } from "@/components/user-type-select";
import type { UserType, UserTypeCatalog } from "@/lib/api-types";
import { userTypeLabel } from "@/lib/user-type-catalog";

import { SupervisorPicker } from "./supervisor-picker";

interface FormState {
  identifierType: "phone" | "email";
  identifierValue: string;
  userType: UserType | null;
  firstName: string;
  lastName: string;
  dateOfBirth: string;
  /** The supervisor's phone number, or null when none is attached. */
  supervisorPhone: string | null;
}

/** The category whose types are merchants (backend: CATEGORY_BUSINESS). */
const MERCHANT_CATEGORY_CODE = "business";

const EMPTY_FORM: FormState = {
  identifierType: "phone",
  identifierValue: "",
  userType: "consumer",
  firstName: "",
  lastName: "",
  dateOfBirth: "",
  supervisorPhone: null,
};

/**
 * Propose a new customer for approval.
 *
 * @param tenantId The active tenant the user is registered under.
 * @param catalog The tenant's user-type catalog — the assignable types, and
 *   the source of each type's supervisor requirement.
 * @param trigger The element that opens the dialog.
 */
export function CreateUserDialog({
  tenantId,
  catalog,
  trigger,
}: {
  tenantId: string;
  catalog: UserTypeCatalog;
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

  const selectedType = catalog.types.find((t) => t.code === form.userType) ?? null;
  // Business IS the merchant category — the same rule the backend applies when
  // it decides whether a user may be bound to a merchant API key. Drives the
  // Epic-17 note below and nothing else.
  const isMerchant = selectedType?.category_code === MERCHANT_CATEGORY_CODE;
  // A type with a parent_type_code sits under a supervisor of that type; every
  // other type has no supervisor slot at all, so the block is absent.
  const supervisorType = selectedType?.parent_type_code ?? null;

  const onSubmit = async () => {
    setErrorBanner(null);
    const identifierValue = form.identifierValue.trim();
    if (!identifierValue) {
      setErrorBanner("Enter a phone number or email address.");
      return;
    }
    if (!form.userType) {
      setErrorBanner("Pick a user type.");
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
      // Omit the key entirely when no supervisor is attached — the backend
      // treats an absent parent and a null one differently on some paths.
      ...(supervisorType && form.supervisorPhone
        ? {
            parent_identifier: {
              identifier_type: "phone" as const,
              identifier_value: form.supervisorPhone,
            },
          }
        : {}),
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

          <UserTypeSelect
            catalog={catalog}
            value={form.userType}
            onChange={(code) =>
              setForm((prev) => ({
                ...prev,
                userType: code,
                // A supervisor confirmed for the old type cannot be assumed
                // valid for the new one — make the operator re-confirm.
                supervisorPhone: null,
              }))
            }
            allowAny={false}
            idPrefix="create-user"
          />

          {supervisorType && (
            <div>
              <Label htmlFor="supervisor-phone">Supervisor (optional)</Label>
              <div className="mt-1">
                <SupervisorPicker
                  key={supervisorType}
                  tenantId={tenantId}
                  catalog={catalog}
                  requiredType={supervisorType}
                  value={form.supervisorPhone}
                  onChange={(phone) => update("supervisorPhone", phone)}
                />
              </div>
            </div>
          )}

          {isMerchant && (
            <p className="text-[11px] text-muted-foreground">
              {userTypeLabel(catalog, form.userType)} is a Business type, so it
              will need a merchant profile (business name, category, provider
              config). Nothing provisions one yet — that lands in Epic 17 — so
              the user is created without one for now.
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
