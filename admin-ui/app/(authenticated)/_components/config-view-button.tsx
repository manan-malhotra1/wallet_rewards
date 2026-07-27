/**
 * "View" affordance for a live config row (Epic 25). Opens a read-only drawer
 * rendering the current config via the shared `ConfigDetail`, plus a
 * "Version history" section listing every APPLIED version of that row. Any
 * prior version can be re-proposed as an update ("Make this version latest"),
 * which routes to the maker-checker approval queue. Reused by the pricing /
 * commission / tax / limit / wallet-limit tables.
 */
"use client";

import { ChevronDown, ChevronRight, Columns2, Eye, History, List } from "lucide-react";
import * as React from "react";

import { ChangeProposedTooltip } from "@/app/(authenticated)/_components/change-proposed-tooltip";
import { ConfigCompare } from "@/app/(authenticated)/_components/config-compare";
import { ConfigDetail } from "@/app/(authenticated)/_components/config-detail";
import {
  loadConfigHistoryAction,
  proposeConfigUpdateAction,
} from "@/app/(authenticated)/config-requests/_actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import { Tooltip } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";
import type { ConfigChangeRequest, ConfigType } from "@/lib/api-types";
import { cn, formatTimestamp } from "@/lib/utils";

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; versions: ConfigChangeRequest[] };

/** Badge for a version's originating operation (create / update). */
function OperationBadge({ operation }: { operation: ConfigChangeRequest["operation"] }) {
  const variant = operation === "create" ? "success" : "secondary";
  return (
    <Badge variant={variant} className="capitalize">
      {operation}
    </Badge>
  );
}

/**
 * One row in the version-history list: expandable to reveal that version's
 * payload, with a "Make this version latest" affordance for prior versions.
 */
function VersionRow({
  version,
  label,
  isCurrent,
  configType,
  serviceNames,
  canPropose,
  changeProposed,
  onRestore,
}: {
  version: ConfigChangeRequest;
  label: string;
  isCurrent: boolean;
  configType: ConfigType;
  serviceNames?: Record<string, string>;
  canPropose: boolean;
  changeProposed: boolean;
  onRestore: () => void;
}) {
  const [expanded, setExpanded] = React.useState(false);
  return (
    <li className="rounded-lg border bg-card">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          className="flex flex-1 items-center gap-2 text-left"
          aria-expanded={expanded}
          aria-label={`${expanded ? "Hide" : "View"} ${label} details`}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-foreground">{label}</span>
            <OperationBadge operation={version.operation} />
            <span className="text-xs text-muted-foreground">
              {formatTimestamp(version.updated_at)}
            </span>
            <span className="text-xs text-muted-foreground">
              {/* A synthesized baseline has no real maker — it reflects the
                  seeded live config, so attribute it to the system. */}
              · {version.synthesized ? "System" : (version.maker_admin_name ?? "Unknown")}
            </span>
          </span>
        </button>
        {!isCurrent &&
          canPropose &&
          // A scope with an open request can't take a second proposal — the
          // restore would be rejected, so disable it and explain why.
          (changeProposed ? (
            <ChangeProposedTooltip>
              <Button variant="outline" size="sm" disabled>
                Make this version latest
              </Button>
            </ChangeProposedTooltip>
          ) : (
            <Button variant="outline" size="sm" onClick={onRestore}>
              Make this version latest
            </Button>
          ))}
      </div>
      {expanded && (
        <div className="border-t px-3 py-3">
          <ConfigDetail
            configType={configType}
            data={version.payload}
            serviceNames={serviceNames}
          />
        </div>
      )}
    </li>
  );
}

/**
 * Read-only View drawer for a live config row, with version history + restore.
 *
 * @param configType Which config domain the row belongs to.
 * @param data The current live config row (rendered at the top of the drawer).
 * @param title Drawer heading.
 * @param serviceNames `{ code: display_name }` so a `transaction_type` renders
 *   as its friendly name in both the detail and every version's payload.
 * @param tenantId Active tenant — scopes the history + restore calls.
 * @param targetConfigId The live row's id; keys its version history.
 * @param canPropose Platform-admin gate for the "Make this version latest"
 *   affordance (the backend re-validates).
 * @param changeProposed Whether an open update/delete request already targets
 *   this row's scope — disables every per-version restore affordance.
 */
export function ConfigViewButton({
  configType,
  data,
  title,
  serviceNames,
  tenantId,
  targetConfigId,
  canPropose,
  changeProposed,
}: {
  configType: ConfigType;
  data: Record<string, unknown>;
  title: string;
  serviceNames?: Record<string, string>;
  tenantId: string;
  targetConfigId: string;
  canPropose: boolean;
  changeProposed: boolean;
}) {
  const { toast } = useToast();
  const [open, setOpen] = React.useState(false);
  const [load, setLoad] = React.useState<LoadState>({ status: "idle" });
  // The version pending a restore confirmation, or null when none is open.
  const [confirming, setConfirming] = React.useState<{
    version: ConfigChangeRequest;
    label: string;
  } | null>(null);
  const [restoring, setRestoring] = React.useState(false);

  // Lazy-load history the first time the drawer opens; nothing is fetched
  // until the operator asks to look at the row.
  React.useEffect(() => {
    if (!open || load.status !== "idle") return;
    setLoad({ status: "loading" });
    loadConfigHistoryAction(tenantId, configType, targetConfigId).then((result) => {
      if (result.ok) {
        setLoad({ status: "loaded", versions: result.versions });
      } else {
        setLoad({
          status: "error",
          message: `${result.errorCode}: ${result.message}`,
        });
      }
    });
  }, [open, load.status, tenantId, configType, targetConfigId]);

  const onConfirmRestore = async () => {
    if (!confirming) return;
    setRestoring(true);
    const result = await proposeConfigUpdateAction(
      tenantId,
      configType,
      targetConfigId,
      confirming.version.payload ?? {},
    );
    setRestoring(false);
    setConfirming(null);
    if (result.ok) {
      toast({ title: "Change proposed — pending approval" });
    } else {
      toast({
        title: "Couldn't propose change",
        description: `${result.errorCode}: ${result.message}`,
        variant: "danger",
      });
    }
  };

  return (
    <>
      <Tooltip content="View">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="View"
          onClick={() => setOpen(true)}
        >
          <Eye className="h-3.5 w-3.5" />
        </Button>
      </Tooltip>
      <Drawer open={open} onOpenChange={setOpen}>
        <DrawerContent>
          <DrawerHeader>
            <DrawerTitle>{title}</DrawerTitle>
          </DrawerHeader>
          <DrawerBody className="space-y-6">
            <ConfigDetail
              configType={configType}
              data={data}
              serviceNames={serviceNames}
            />
            <section className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <History className="h-4 w-4 text-muted-foreground" />
                Version history
              </h3>
              <VersionHistory
                load={load}
                configType={configType}
                serviceNames={serviceNames}
                canPropose={canPropose}
                changeProposed={changeProposed}
                onRestore={(version, label) => setConfirming({ version, label })}
              />
            </section>
          </DrawerBody>
        </DrawerContent>
      </Drawer>

      <Dialog
        open={confirming !== null}
        onOpenChange={(o) => !o && setConfirming(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Make this version latest?</DialogTitle>
            <DialogDescription>
              This re-proposes {confirming?.label}&apos;s values as an update. It
              routes to the approval queue and only goes live once a second admin
              approves — nothing changes immediately.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setConfirming(null)}
              disabled={restoring}
            >
              Cancel
            </Button>
            <Button onClick={onConfirmRestore} disabled={restoring}>
              {restoring ? "Proposing…" : "Propose change"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** Render the loading / error / empty / loaded states of the version list. */
function VersionHistory({
  load,
  configType,
  serviceNames,
  canPropose,
  changeProposed,
  onRestore,
}: {
  load: LoadState;
  configType: ConfigType;
  serviceNames?: Record<string, string>;
  canPropose: boolean;
  changeProposed: boolean;
  onRestore: (version: ConfigChangeRequest, label: string) => void;
}) {
  const [comparing, setComparing] = React.useState(false);

  if (load.status === "loading" || load.status === "idle") {
    return <p className="text-sm text-muted-foreground">Loading versions…</p>;
  }
  if (load.status === "error") {
    return <p className="text-sm text-destructive">{load.message}</p>;
  }
  if (load.versions.length === 0) {
    return <p className="text-sm text-muted-foreground">No versions yet.</p>;
  }
  // A single version (a lone applied change, or the synthesized "current"
  // baseline for a seed-created config) still renders as one row — there's just
  // nothing to compare against, so the Compare toggle is suppressed.
  if (load.versions.length === 1) {
    return (
      <VersionList
        versions={load.versions}
        configType={configType}
        serviceNames={serviceNames}
        canPropose={canPropose}
        changeProposed={changeProposed}
        onRestore={onRestore}
      />
    );
  }

  return (
    <div className="space-y-3">
      {/* Comparison is opt-in; the version list stays the default view. */}
      <button
        type="button"
        onClick={() => setComparing((v) => !v)}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        {comparing ? (
          <>
            <List className="h-3.5 w-3.5" aria-hidden="true" />
            Show list
          </>
        ) : (
          <>
            <Columns2 className="h-3.5 w-3.5" aria-hidden="true" />
            Compare versions
          </>
        )}
      </button>
      {comparing ? (
        <VersionCompare
          versions={load.versions}
          configType={configType}
          serviceNames={serviceNames}
        />
      ) : (
        <VersionList
          versions={load.versions}
          configType={configType}
          serviceNames={serviceNames}
          canPropose={canPropose}
          changeProposed={changeProposed}
          onRestore={onRestore}
        />
      )}
    </div>
  );
}

/** Number applied versions oldest-first (v1..vN); the last is the live config. */
function versionLabel(index: number, total: number): string {
  return index === total - 1 ? `Active · v${index + 1}` : `v${index + 1}`;
}

/** The default view: every applied version, newest-first, expandable + restorable. */
function VersionList({
  versions,
  configType,
  serviceNames,
  canPropose,
  changeProposed,
  onRestore,
}: {
  versions: ConfigChangeRequest[];
  configType: ConfigType;
  serviceNames?: Record<string, string>;
  canPropose: boolean;
  changeProposed: boolean;
  onRestore: (version: ConfigChangeRequest, label: string) => void;
}) {
  const currentIndex = versions.length - 1;
  const rows = versions
    .map((version, index) => ({
      version,
      index,
      isCurrent: index === currentIndex,
      // A synthesized baseline (seed-created config, no applied history) IS the
      // current live config — label it as such rather than "Active · v1".
      label: version.synthesized
        ? "Current (baseline)"
        : versionLabel(index, versions.length),
    }))
    .reverse();

  return (
    <ul className="space-y-2">
      {rows.map(({ version, index, isCurrent, label }) => (
        <VersionRow
          key={version.id ?? index}
          version={version}
          label={label}
          isCurrent={isCurrent}
          configType={configType}
          serviceNames={serviceNames}
          canPropose={canPropose}
          changeProposed={changeProposed}
          onRestore={() => onRestore(version, label)}
        />
      ))}
    </ul>
  );
}

/** Version chips for picking one side of the comparison (v1..vN). */
function VersionChips({
  versions,
  selected,
  onSelect,
}: {
  versions: ConfigChangeRequest[];
  selected: number;
  onSelect: (index: number) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {versions.map((version, index) => (
        <button
          key={version.id ?? index}
          type="button"
          onClick={() => onSelect(index)}
          className={cn(
            "rounded-md px-2 py-0.5 text-xs transition-colors",
            index === selected
              ? "bg-primary font-medium text-primary-foreground"
              : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
          )}
        >
          v{index + 1}
        </button>
      ))}
    </div>
  );
}

/**
 * Opt-in comparison: pick any two applied versions (base + compare) and render
 * a side-by-side diff. Defaults to the previous version vs the current one.
 */
function VersionCompare({
  versions,
  configType,
  serviceNames,
}: {
  versions: ConfigChangeRequest[];
  configType: ConfigType;
  serviceNames?: Record<string, string>;
}) {
  const currentIndex = versions.length - 1;
  const [baseIndex, setBaseIndex] = React.useState(currentIndex - 1);
  const [compareIndex, setCompareIndex] = React.useState(currentIndex);

  const base = versions[baseIndex];
  const compare = versions[compareIndex];

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1">
          <span className="text-xs text-muted-foreground">Base</span>
          <VersionChips
            versions={versions}
            selected={baseIndex}
            onSelect={setBaseIndex}
          />
        </div>
        <div className="space-y-1">
          <span className="text-xs text-muted-foreground">Compare</span>
          <VersionChips
            versions={versions}
            selected={compareIndex}
            onSelect={setCompareIndex}
          />
        </div>
      </div>
      {baseIndex === compareIndex ? (
        <p className="text-sm text-muted-foreground">
          Pick two different versions to compare.
        </p>
      ) : (
        <ConfigCompare
          configType={configType}
          left={{
            label: versionLabel(baseIndex, versions.length),
            data: base?.payload ?? null,
          }}
          right={{
            label: versionLabel(compareIndex, versions.length),
            data: compare?.payload ?? null,
          }}
          serviceNames={serviceNames}
        />
      )}
    </div>
  );
}
