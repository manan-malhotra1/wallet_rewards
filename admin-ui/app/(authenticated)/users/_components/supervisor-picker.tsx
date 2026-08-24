/**
 * <SupervisorPicker> — attach a supervisor to a child-type user by phone
 * lookup (spec §7.4).
 *
 * Deliberately not a free-text id, and deliberately not a dropdown of every
 * super agent, which stops scaling past a few dozen. The operator types a
 * phone number, presses Look up, and CONFIRMS a person — name, type and masked
 * phone — before the dialog accepts them. Attaching the wrong supervisor is
 * commercially meaningful (their commission flows to that person), so the
 * confirmation step is the point of the component, not decoration.
 *
 * The value reported upward is the phone number, never the resolved id: the
 * create payload carries `parent_identifier` so the backend re-resolves and
 * re-validates the person when the proposal is approved.
 */
"use client";

import { Search, X } from "lucide-react";
import * as React from "react";

import {
  lookupUserAction,
  type LookedUpUser,
} from "@/app/(authenticated)/users/_actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { UserTypeCatalog } from "@/lib/api-types";
import { userTypeLabel } from "@/lib/user-type-catalog";

/**
 * A phone field, a Look up action, and a confirmed-person panel.
 *
 * @param tenantId The active tenant — resolution is tenant-scoped.
 * @param catalog The tenant's user-type catalog, for labelling the required
 *   type and whatever type the resolved person actually turned out to be.
 * @param requiredType The type code a supervisor of this user must have, read
 *   off the child type's `parent_type_code`.
 * @param value The attached supervisor's phone number, or null when none is
 *   attached (the normal case — the field is optional).
 * @param onChange Fires with the phone number once a person of the right type
 *   is confirmed, and with null when the operator clears the field.
 */
export function SupervisorPicker({
  tenantId,
  catalog,
  requiredType,
  value,
  onChange,
}: {
  tenantId: string;
  catalog: UserTypeCatalog;
  requiredType: string;
  value: string | null;
  onChange: (phone: string | null) => void;
}) {
  const [phone, setPhone] = React.useState(value ?? "");
  const [resolved, setResolved] = React.useState<LookedUpUser | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [looking, setLooking] = React.useState(false);
  const requiredLabel = userTypeLabel(catalog, requiredType);

  const onLookUp = async () => {
    setError(null);
    setResolved(null);
    setLooking(true);
    const result = await lookupUserAction(tenantId, phone);
    setLooking(false);

    if (!result.ok) {
      setError(result.message);
      onChange(null);
      return;
    }
    setResolved(result.user);
    if (result.user.user_type !== requiredType) {
      // Name the type required rather than failing generically — the operator
      // has almost certainly typed the right person's number for the wrong
      // role, and needs to know which role to go and find.
      setError(`Supervisor must be a ${requiredLabel}.`);
      onChange(null);
      return;
    }
    onChange(phone.trim());
  };

  const onClear = () => {
    setPhone("");
    setResolved(null);
    setError(null);
    onChange(null);
  };

  const attached = resolved !== null && error === null;

  return (
    <div className="space-y-2 rounded-md border border-dashed p-3">
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Label htmlFor="supervisor-phone">Supervisor&apos;s phone</Label>
          <Input
            id="supervisor-phone"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            onKeyDown={(e) => {
              // Enter inside a dialog would otherwise submit the whole form,
              // proposing a user before the supervisor was ever confirmed.
              if (e.key === "Enter") {
                e.preventDefault();
                void onLookUp();
              }
            }}
            placeholder="+27 82 555 0142"
            autoComplete="off"
            disabled={attached}
            className="mt-1"
          />
        </div>
        {attached ? (
          <Button type="button" variant="outline" size="md" onClick={onClear}>
            <X className="h-3.5 w-3.5" aria-hidden="true" />
            Clear
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="md"
            onClick={onLookUp}
            disabled={looking || !phone.trim()}
          >
            <Search className="h-3.5 w-3.5" aria-hidden="true" />
            {looking ? "Looking up…" : "Look up"}
          </Button>
        )}
      </div>

      {resolved && (
        <div className="rounded-md bg-muted/40 px-3 py-2">
          <p className="text-sm font-medium">{resolved.full_name ?? "Unnamed user"}</p>
          <p className="text-xs text-muted-foreground">
            {userTypeLabel(catalog, resolved.user_type)} ·{" "}
            <span className="font-mono">{resolved.masked_phone}</span>
          </p>
        </div>
      )}

      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          {attached
            ? "Confirmed — this person will be re-checked when the request is approved."
            : `Optional. Must be a ${requiredLabel}; look them up to confirm before attaching.`}
        </p>
      )}
    </div>
  );
}
