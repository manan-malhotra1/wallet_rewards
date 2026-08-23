/**
 * <EditServicePolicyDialog> — change WHO (user types) and WHICH CHANNELS may
 * initiate an existing service.
 *
 * The catalog's inline row edit only covers display_name + status, so this is
 * the affordance admins use to revise the access policy after creation
 * (Phase 2). Each dimension has three states — unrestricted (`null`), an
 * allow-list, or restrict-to-none (`[]`) — so the control pairs a "Restrict"
 * toggle (off = null) with a chip group (on + no chips = `[]`). Only the
 * dimensions the admin actually changes are sent; an untouched control is
 * omitted from the PATCH, preserving its stored null-vs-[] value.
 */
"use client";

import * as React from "react";

import { updateServiceAction } from "@/app/(authenticated)/services/_actions";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import {
  SERVICE_CHANNELS,
  type Service,
  type UserTypeCatalog,
} from "@/lib/api-types";
import type { UpdateServicePayload } from "@/lib/api-endpoints";

import { ChipGroup } from "./policy-controls";

/** Add/remove a value from a selection array (immutably). */
function toggleValue(current: string[], value: string): string[] {
  return current.includes(value)
    ? current.filter((v) => v !== value)
    : [...current, value];
}

/**
 * Fold a restrict-toggle + selection back into the wire value: `null` when
 * unrestricted, otherwise the (possibly empty) allow-list.
 */
function toPolicy(restricted: boolean, selected: string[]): string[] | null {
  return restricted ? selected : null;
}

/** Order-insensitive equality for two policy values (null or allow-list). */
function samePolicy(a: string[] | null, b: string[] | null): boolean {
  if (a === null || b === null) return a === b;
  if (a.length !== b.length) return false;
  const set = new Set(a);
  return b.every((v) => set.has(v));
}

export function EditServicePolicyDialog({
  service,
  tenantId,
  trigger,
  catalog,
}: {
  service: Service;
  tenantId: string;
  trigger: React.ReactNode;
  /** The tenant's user-type catalog, fetched by the page's server component. */
  catalog: UserTypeCatalog;
}) {
  const [open, setOpen] = React.useState(false);
  const [utRestricted, setUtRestricted] = React.useState(false);
  const [userTypes, setUserTypes] = React.useState<string[]>([]);
  const [chRestricted, setChRestricted] = React.useState(false);
  const [channels, setChannels] = React.useState<string[]>([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  // Every active type is selectable; the allow-list is a subset of the catalog
  // rather than a fixed enum, so a tenant's own type can be granted access.
  const userTypeOptions = React.useMemo(
    () => catalog.types.filter((t) => t.status === "active").map((t) => t.code),
    [catalog],
  );

  // Seed the controls from the row each time the dialog opens so edits always
  // start from the persisted policy, never a stale draft.
  React.useEffect(() => {
    if (open) {
      setUtRestricted(service.allowed_user_types !== null);
      setUserTypes(service.allowed_user_types ?? []);
      setChRestricted(service.allowed_channels !== null);
      setChannels(service.allowed_channels ?? []);
      setError(null);
    }
  }, [open, service.allowed_user_types, service.allowed_channels]);

  async function onSubmit() {
    setError(null);
    // Only send the dimensions that actually changed — leaving a field out of
    // the PATCH preserves its stored value (including the null-vs-[] distinction).
    const payload: UpdateServicePayload = {};
    const nextUt = toPolicy(utRestricted, userTypes);
    const nextCh = toPolicy(chRestricted, channels);
    if (!samePolicy(nextUt, service.allowed_user_types)) {
      payload.allowed_user_types = nextUt;
    }
    if (!samePolicy(nextCh, service.allowed_channels)) {
      payload.allowed_channels = nextCh;
    }

    if (Object.keys(payload).length === 0) {
      setOpen(false);
      return;
    }

    setSubmitting(true);
    const res = await updateServiceAction(service.id, tenantId, payload);
    setSubmitting(false);
    if (res.ok) {
      toast({ title: "Policy updated", description: service.display_name });
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
          <DialogTitle>Access policy</DialogTitle>
          <DialogDescription>
            Control who and which channels may initiate{" "}
            <span className="font-medium">{service.display_name}</span>. Leave a
            dimension unrestricted to allow everything.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Checkbox
              checked={utRestricted}
              onChange={(e) => setUtRestricted(e.target.checked)}
              disabled={submitting}
              label="Restrict who can initiate"
            />
            {utRestricted ? (
              <>
                <ChipGroup
                  ariaLabel="Who can initiate"
                  options={userTypeOptions}
                  catalog={catalog}
                  selected={userTypes}
                  onToggle={(v) => setUserTypes((cur) => toggleValue(cur, v))}
                  disabled={submitting}
                />
                <p className="mt-1 text-[11px] text-[--color-text-3]">
                  Select the allowed user types. None selected = operator-only.
                </p>
              </>
            ) : (
              <p className="mt-1 text-[11px] text-[--color-text-3]">
                All user types allowed.
              </p>
            )}
          </div>

          <div>
            <Checkbox
              checked={chRestricted}
              onChange={(e) => setChRestricted(e.target.checked)}
              disabled={submitting}
              label="Restrict channels"
            />
            {chRestricted ? (
              <>
                <ChipGroup
                  ariaLabel="Channels"
                  options={SERVICE_CHANNELS}
                  selected={channels}
                  onToggle={(v) => setChannels((cur) => toggleValue(cur, v))}
                  disabled={submitting}
                />
                <p className="mt-1 text-[11px] text-[--color-text-3]">
                  Select the allowed channels. None selected = restrict to none.
                </p>
              </>
            ) : (
              <p className="mt-1 text-[11px] text-[--color-text-3]">
                All channels allowed.
              </p>
            )}
          </div>

          {error && <ErrorBanner title="Couldn't update" description={error} />}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Saving…" : "Save policy"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
