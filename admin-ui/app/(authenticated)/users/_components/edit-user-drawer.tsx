/**
 * <EditUserDrawer> — inline "Edit user" affordance on the detail page (Epic 3).
 *
 * The Edit button opens a drawer exposing ONLY the editable fields (first name,
 * last name, status, user type); identifiers are shown read-only. On save it
 * PROPOSES an update_user operation (does NOT mutate the user directly) with
 * just the changed fields, then confirms it's awaiting approval. If the user
 * already has an open (PENDING / CHANGES_REQUESTED) update request, the drawer
 * surfaces that instead of allowing a duplicate.
 */
"use client";

import { Pencil } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { proposeUpdateUserAction } from "@/app/(authenticated)/users/_actions";
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
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
import type { UserIdentifier, UserType, UserTypeCatalog } from "@/lib/api-types";

/** An open update request already awaiting review for this user. */
export interface OpenUpdateRequest {
  id: string;
  status: string;
}

interface Current {
  firstName: string;
  lastName: string;
  status: "active" | "suspended";
  userType: UserType;
}

/**
 * The inline "Edit user" drawer.
 *
 * @param userId The user being edited.
 * @param tenantId The active tenant.
 * @param current The user's current editable values, used to reset the form
 *   and to send only what actually changed.
 * @param identifiers Shown read-only — identifiers are not editable here.
 * @param openUpdate An update already awaiting review, which blocks a second.
 * @param catalog The tenant's user-type catalog; null when it failed to load,
 *   in which case the type is left alone rather than offered as a blank list.
 */
export function EditUserDrawer({
  userId,
  tenantId,
  current,
  identifiers,
  openUpdate,
  catalog,
}: {
  userId: string;
  tenantId: string;
  current: Current;
  identifiers: UserIdentifier[];
  openUpdate: OpenUpdateRequest | null;
  catalog: UserTypeCatalog | null;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [open, setOpen] = React.useState(false);
  const [firstName, setFirstName] = React.useState(current.firstName);
  const [lastName, setLastName] = React.useState(current.lastName);
  const [status, setStatus] = React.useState<"active" | "suspended">(current.status);
  const [userType, setUserType] = React.useState<UserType | null>(current.userType);
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);

  // Reset the form to the user's current values whenever the drawer opens.
  React.useEffect(() => {
    if (open) {
      setFirstName(current.firstName);
      setLastName(current.lastName);
      setStatus(current.status);
      setUserType(current.userType);
      setErrorBanner(null);
    }
  }, [open, current]);

  const onSubmit = async () => {
    setErrorBanner(null);
    // Send only the fields the maker actually changed — a no-op is rejected.
    const changes: {
      first_name?: string;
      last_name?: string;
      status?: "active" | "suspended";
      user_type?: string;
    } = {};
    if (firstName.trim() !== current.firstName) changes.first_name = firstName.trim();
    if (lastName.trim() !== current.lastName) changes.last_name = lastName.trim();
    if (status !== current.status) changes.status = status;
    if (userType && userType !== current.userType) changes.user_type = userType;

    if (Object.keys(changes).length === 0) {
      setErrorBanner("Change at least one field before submitting.");
      return;
    }

    setSubmitting(true);
    const result = await proposeUpdateUserAction({
      tenantId,
      target_user_id: userId,
      ...changes,
    });
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: "Edit request submitted",
      description: "Awaiting approval — track it under User approvals.",
    });
    setOpen(false);
    router.push("/user-operations");
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        className="gap-1.5 border-primary-foreground/30 bg-primary-foreground/10 text-primary-foreground hover:bg-primary-foreground/20"
      >
        <Pencil className="h-3.5 w-3.5" />
        Edit
      </Button>

      <Drawer open={open} onOpenChange={setOpen}>
        <DrawerContent>
          <DrawerHeader>
            <DrawerTitle>Edit user</DrawerTitle>
            <p className="text-xs text-muted-foreground">
              Changes are submitted for approval — nothing is applied until a
              user approver signs off.
            </p>
          </DrawerHeader>
          <DrawerBody className="space-y-5">
            {openUpdate ? (
              <ErrorBanner
                title="An edit is already awaiting approval"
                description={`This user has an open update request (${openUpdate.status}). Resolve it under User approvals before proposing another change.`}
              />
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label htmlFor="edit-fn">First name</Label>
                    <Input
                      id="edit-fn"
                      value={firstName}
                      onChange={(e) => setFirstName(e.target.value)}
                      placeholder="Jane"
                    />
                  </div>
                  <div>
                    <Label htmlFor="edit-ln">Last name</Label>
                    <Input
                      id="edit-ln"
                      value={lastName}
                      onChange={(e) => setLastName(e.target.value)}
                      placeholder="Mokoena"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="col-span-2">
                    <Label htmlFor="edit-status">Status</Label>
                    <Select
                      value={status}
                      onValueChange={(v) => setStatus(v as "active" | "suspended")}
                    >
                      <SelectTrigger id="edit-status">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="active">Active</SelectItem>
                        <SelectItem value="suspended">Suspended</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                {catalog && (
                  <UserTypeSelect
                    catalog={catalog}
                    value={userType}
                    onChange={setUserType}
                    allowAny={false}
                    idPrefix="edit-user"
                  />
                )}
                <div>
                  <Label>Identifiers (read-only)</Label>
                  <ul className="mt-1 space-y-1">
                    {identifiers.length === 0 ? (
                      <li className="text-sm text-muted-foreground">None</li>
                    ) : (
                      identifiers.map((ident) => (
                        <li
                          key={`${ident.identifier_type}-${ident.identifier_value}`}
                          className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-1.5"
                        >
                          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                            {ident.identifier_type}
                          </span>
                          <span className="font-mono text-xs">
                            {ident.identifier_value}
                          </span>
                        </li>
                      ))
                    )}
                  </ul>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    Identifiers can't be edited here.
                  </p>
                </div>
                {errorBanner && (
                  <ErrorBanner title="Could not submit" description={errorBanner} />
                )}
              </>
            )}
          </DrawerBody>
          <DrawerFooter>
            <Button variant="ghost" disabled={submitting} onClick={() => setOpen(false)}>
              {openUpdate ? "Close" : "Cancel"}
            </Button>
            {openUpdate ? (
              <Button onClick={() => router.push("/user-operations")}>
                Go to User approvals
              </Button>
            ) : (
              <Button disabled={submitting} onClick={onSubmit}>
                {submitting ? "Submitting…" : "Submit for approval"}
              </Button>
            )}
          </DrawerFooter>
        </DrawerContent>
      </Drawer>
    </>
  );
}
