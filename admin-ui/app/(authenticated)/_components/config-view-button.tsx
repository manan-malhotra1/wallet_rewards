/**
 * "View" affordance for a live config row (Epic 25). Opens a read-only drawer
 * rendering the current config via the shared `ConfigDetail`, plus a
 * "Version history" section listing every APPLIED version of that row. Any
 * prior version can be re-proposed as an update ("Make this version latest"),
 * which routes to the maker-checker approval queue. Reused by the pricing /
 * commission / tax / limit / wallet-limit tables.
 */
"use client";

import { ChevronDown, ChevronRight, Eye, History } from "lucide-react";
import * as React from "react";

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
import { formatTimestamp } from "@/lib/utils";

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
  onRestore,
}: {
  version: ConfigChangeRequest;
  label: string;
  isCurrent: boolean;
  configType: ConfigType;
  serviceNames?: Record<string, string>;
  canPropose: boolean;
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
            {isCurrent && <Badge variant="info">Live</Badge>}
            <OperationBadge operation={version.operation} />
            <span className="text-xs text-muted-foreground">
              {formatTimestamp(version.updated_at)}
            </span>
            <span className="text-xs text-muted-foreground">
              · {version.maker_admin_name ?? "Unknown"}
            </span>
          </span>
        </button>
        {!isCurrent && canPropose && (
          <Button variant="outline" size="sm" onClick={onRestore}>
            Make this version latest
          </Button>
        )}
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
 */
export function ConfigViewButton({
  configType,
  data,
  title,
  serviceNames,
  tenantId,
  targetConfigId,
  canPropose,
}: {
  configType: ConfigType;
  data: Record<string, unknown>;
  title: string;
  serviceNames?: Record<string, string>;
  tenantId: string;
  targetConfigId: string;
  canPropose: boolean;
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
  onRestore,
}: {
  load: LoadState;
  configType: ConfigType;
  serviceNames?: Record<string, string>;
  canPropose: boolean;
  onRestore: (version: ConfigChangeRequest, label: string) => void;
}) {
  if (load.status === "loading" || load.status === "idle") {
    return <p className="text-sm text-muted-foreground">Loading versions…</p>;
  }
  if (load.status === "error") {
    return <p className="text-sm text-destructive">{load.message}</p>;
  }
  if (load.versions.length <= 1) {
    return <p className="text-sm text-muted-foreground">No prior versions.</p>;
  }

  // Backend returns oldest-first; the last entry is the current live config.
  // Display newest-first while keeping each version's chronological label.
  const currentIndex = load.versions.length - 1;
  const rows = load.versions
    .map((version, index) => ({
      version,
      index,
      isCurrent: index === currentIndex,
      label: index === currentIndex ? "Current" : `v${index + 1}`,
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
          onRestore={() => onRestore(version, label)}
        />
      ))}
    </ul>
  );
}
