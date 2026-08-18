/**
 * <CreateServiceDialog> — admin form to add a DERIVED service to the catalog.
 *
 * Only derived services are creatable. The nine base services are the real
 * money flows the backend knows how to execute; they ship with the platform
 * and are provisioned per tenant. A derived service is an alias of one base:
 * its own name, pricing, limits and access policy, running the base's
 * execution path. That is why "Based on" is required and immutable — changing
 * it later would silently repoint live pricing and limits at a different flow.
 *
 * Code is locked once created (it's the immutable identifier stored in
 * downstream tables) so this dialog only appears for new entries; later
 * edits use the inline row actions in <ServicesTable>.
 */
"use client";

import * as React from "react";

import { createServiceAction } from "@/app/(authenticated)/services/_actions";
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
import { SERVICE_CHANNELS, USER_TYPES, type Service } from "@/lib/api-types";

import { ChipGroup } from "./policy-controls";

const CODE_PATTERN = /^[a-z][a-z0-9_]*$/;

/** Add/remove a value from a selection array (immutably). */
function toggleValue(current: string[], value: string): string[] {
  return current.includes(value)
    ? current.filter((v) => v !== value)
    : [...current, value];
}

/**
 * The bases a new derived service may point at: server-marked `derivable` and
 * currently active. `derivable` is computed by the backend from its service
 * registry — deliberately not re-derived here, because the rule excludes
 * specific bases (`change_pin`) and a TypeScript copy would drift.
 */
export function derivableBases(services: Service[]): Service[] {
  return services
    .filter((s) => s.derivable && s.status === "active")
    .sort((a, b) => a.display_name.localeCompare(b.display_name));
}

/**
 * Which values a derived service may pick on one policy dimension.
 *
 * The backend enforces narrowing-only: a derived service may never permit a
 * user type or channel its base excludes. So when the base carries an
 * allow-list, that list IS the option set; when the base is unrestricted
 * (`null`), everything is on the table.
 */
export function allowedOptions(
  baseValues: string[] | null,
  all: readonly string[],
): readonly string[] {
  return baseValues === null ? all : baseValues;
}

/**
 * Translate a chip selection into the value the API expects for one dimension.
 *
 * The empty selection is genuinely ambiguous and the two cases are NOT
 * interchangeable:
 *  - base unrestricted → `null`, meaning "inherit the base's openness".
 *  - base restricted → there is no safe reading. `null` would be WIDER than
 *    the base, and the backend also rejects `[]` here (its narrowing check
 *    treats empty and null alike), so an empty selection cannot be submitted
 *    at all. `submissionError` blocks it in the form instead of letting the
 *    admin discover it as a 422.
 */
export function policyValue(
  selected: string[],
  baseValues: string[] | null,
): string[] | null {
  if (selected.length > 0) return selected;
  return baseValues === null ? null : [];
}

export function CreateServiceDialog({
  tenantId,
  services,
  trigger,
}: {
  tenantId: string;
  services: Service[];
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [baseCode, setBaseCode] = React.useState("");
  const [code, setCode] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [userTypes, setUserTypes] = React.useState<string[]>([]);
  const [channels, setChannels] = React.useState<string[]>([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  const bases = React.useMemo(() => derivableBases(services), [services]);
  const base = bases.find((b) => b.code === baseCode) ?? null;

  const userTypeOptions = allowedOptions(
    base?.allowed_user_types ?? null,
    USER_TYPES,
  );
  const channelOptions = allowedOptions(base?.allowed_channels ?? null, SERVICE_CHANNELS);

  React.useEffect(() => {
    if (!open) {
      setBaseCode("");
      setCode("");
      setDisplayName("");
      setDescription("");
      setUserTypes([]);
      setChannels([]);
      setError(null);
    }
  }, [open]);

  /**
   * Picking a base seeds the policy with the base's own allow-lists — the
   * widest legal starting point — so the common "same audience as the base,
   * different price" case needs no chip clicks, and any edit from here can
   * only narrow. Also clears selections that the new base forbids.
   */
  function onBaseChange(next: string) {
    setBaseCode(next);
    const picked = bases.find((b) => b.code === next) ?? null;
    setUserTypes(picked?.allowed_user_types ?? []);
    setChannels(picked?.allowed_channels ?? []);
    setError(null);
  }

  /**
   * Form-level validation message, or null when the form may be submitted.
   * Kept as a derived value so the same rule drives both the inline hint and
   * the submit guard.
   */
  const submissionError = ((): string | null => {
    if (!baseCode) return "Choose the base service this one runs on.";
    if (!CODE_PATTERN.test(code))
      return "Code must be lowercase letters, numbers, and underscores; start with a letter.";
    if (!displayName.trim()) return "Display name is required.";
    if (base?.allowed_user_types !== null && userTypes.length === 0)
      return `Pick at least one user type. "${base?.display_name}" is itself restricted, so this service cannot be open to all.`;
    if (base?.allowed_channels !== null && channels.length === 0)
      return `Pick at least one channel. "${base?.display_name}" is itself restricted, so this service cannot be open to all.`;
    return null;
  })();

  async function onSubmit() {
    if (submissionError) {
      setError(submissionError);
      return;
    }
    setError(null);
    setSubmitting(true);
    const res = await createServiceAction({
      tenant_id: tenantId,
      code,
      display_name: displayName.trim(),
      description: description.trim() || undefined,
      base_service_code: baseCode,
      allowed_user_types: policyValue(userTypes, base?.allowed_user_types ?? null),
      allowed_channels: policyValue(channels, base?.allowed_channels ?? null),
    });
    setSubmitting(false);
    if (res.ok) {
      toast({ title: "Service created", description: displayName });
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
          <DialogTitle>New service</DialogTitle>
          <DialogDescription>
            A variant of an existing service — its own name, pricing and limits,
            running the same underlying flow. The base services themselves ship
            with the platform and can&apos;t be created here.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label htmlFor="svc-base">Based on</Label>
            <Select value={baseCode} onValueChange={onBaseChange} disabled={submitting}>
              <SelectTrigger id="svc-base" className="mt-1">
                <SelectValue placeholder="Choose a base service" />
              </SelectTrigger>
              <SelectContent>
                {bases.map((b) => (
                  <SelectItem key={b.code} value={b.code}>
                    {b.display_name}{" "}
                    <span className="font-mono text-[11px] text-[--color-text-3]">
                      {b.code}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="mt-1 text-[11px] text-[--color-text-3]">
              {bases.length === 0
                ? "No base services are active for this tenant, so there is nothing to derive from yet."
                : "Determines how the money actually moves. Cannot be changed later."}
            </p>
          </div>
          <div>
            <Label htmlFor="svc-code">Code</Label>
            <Input
              id="svc-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder={baseCode ? `${baseCode}_variant` : "p2p_diaspora"}
              className="mt-1 font-mono text-[12px]"
            />
            <p className="mt-1 text-[11px] text-[--color-text-3]">
              Lowercase letters, digits, underscores. Cannot be changed later.
            </p>
          </div>
          <div>
            <Label htmlFor="svc-name">Display name</Label>
            <Input
              id="svc-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Diaspora Transfer"
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="svc-desc">Description (optional)</Label>
            <Input
              id="svc-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Send money home at diaspora pricing."
              className="mt-1"
            />
          </div>
          <div>
            <Label>Who can initiate</Label>
            <ChipGroup
              ariaLabel="Who can initiate"
              options={userTypeOptions}
              selected={userTypes}
              onToggle={(v) => setUserTypes((cur) => toggleValue(cur, v))}
              disabled={submitting || !baseCode}
            />
            <p className="mt-1 text-[11px] text-[--color-text-3]">
              {!baseCode
                ? "Choose a base service first."
                : base?.allowed_user_types === null
                  ? "Leave empty = all user types allowed."
                  : "Only the user types its base permits are offered."}
            </p>
          </div>
          <div>
            <Label>Channels</Label>
            <ChipGroup
              ariaLabel="Channels"
              options={channelOptions}
              selected={channels}
              onToggle={(v) => setChannels((cur) => toggleValue(cur, v))}
              disabled={submitting || !baseCode}
            />
            <p className="mt-1 text-[11px] text-[--color-text-3]">
              {!baseCode
                ? "Choose a base service first."
                : base?.allowed_channels === null
                  ? "Leave empty = all channels allowed."
                  : "Only the channels its base permits are offered."}
            </p>
          </div>
          <p className="text-[11px] text-[--color-text-3]">
            A new service can&apos;t transact until it has its own pricing and
            limit configuration, and a role that permits it.
          </p>
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
