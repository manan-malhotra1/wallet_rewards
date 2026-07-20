/**
 * <AuditTable> — plain-language list of audit entries answering WHO / WHEN /
 * WHERE / WHOSE / WHAT. Clicking a row opens a <Drawer> with a humanized
 * before→after diff (raw JSON stays available behind an expander).
 */
"use client";

import { ChevronRight } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import {
  actorLocationLabel,
  actorRoleLabel,
  auditActionLabel,
  diffStates,
} from "@/lib/audit-labels";
import { formatTimestamp, shortId } from "@/lib/utils";

import type { AuditEntry } from "@/lib/api-types";

function actorBadgeTone(actorType: AuditEntry["actor_type"]) {
  if (actorType === "admin") return "brand" as const;
  if (actorType === "user") return "accent" as const;
  return "neutral" as const;
}

/** WHO: the actor's display name (never a bare UUID when a name resolved). */
function actorDisplay(entry: AuditEntry): string {
  return entry.actor_name ?? shortId(entry.actor_id);
}

/** WHOSE: the affected party — named user, or entity type + short id. */
function affectedDisplay(entry: AuditEntry): string {
  if (entry.entity_type === "user") {
    return `for ${entry.entity_name ?? shortId(entry.entity_id)}`;
  }
  return `${entry.entity_type} ${shortId(entry.entity_id)}`;
}

export function AuditTable({ entries }: { entries: AuditEntry[] }) {
  const [selected, setSelected] = React.useState<AuditEntry | null>(null);
  const [showRaw, setShowRaw] = React.useState(false);

  React.useEffect(() => {
    setShowRaw(false);
  }, [selected]);

  return (
    <>
      <div className="overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface-1]">
        <Table>
          <TableHead>
            <TableRow>
              <TableHeaderCell className="w-[140px]">When</TableHeaderCell>
              <TableHeaderCell>What</TableHeaderCell>
              <TableHeaderCell>Who</TableHeaderCell>
              <TableHeaderCell>Whose</TableHeaderCell>
              <TableHeaderCell className="w-[40px]"> </TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {entries.map((entry) => (
              <TableRow
                key={entry.id}
                onClick={() => setSelected(entry)}
                className="cursor-pointer"
              >
                <TableCell className="font-mono text-[11px] text-[--color-text-2]">
                  {formatTimestamp(entry.created_at)}
                </TableCell>
                <TableCell className="font-medium text-[--color-text-1]">
                  {auditActionLabel(entry)}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Badge tone={actorBadgeTone(entry.actor_type)}>
                      {actorRoleLabel(entry.actor_type)}
                    </Badge>
                    <span className="text-[12px] text-[--color-text-2]">
                      {actorDisplay(entry)}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="text-[12px] text-[--color-text-2]">
                  {affectedDisplay(entry)}
                </TableCell>
                <TableCell>
                  <ChevronRight className="h-3.5 w-3.5 text-[--color-text-3]" />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Drawer open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        {selected && (
          <DrawerContent>
            <DrawerHeader>
              <DrawerTitle>{auditActionLabel(selected)}</DrawerTitle>
              <DrawerDescription>
                {affectedDisplay(selected)} · {formatTimestamp(selected.created_at)}
              </DrawerDescription>
            </DrawerHeader>
            <DrawerBody>
              <dl className="grid grid-cols-2 gap-3 text-[12px]">
                <div>
                  <dt className="text-[--color-text-3]">Who</dt>
                  <dd>
                    {actorDisplay(selected)}{" "}
                    <span className="text-[--color-text-3]">
                      ({actorRoleLabel(selected.actor_type)})
                    </span>
                  </dd>
                </div>
                <div>
                  <dt className="text-[--color-text-3]">Where</dt>
                  <dd>{actorLocationLabel(selected.actor_type)}</dd>
                </div>
                <div>
                  <dt className="text-[--color-text-3]">IP</dt>
                  <dd className="font-mono">{selected.ip_address ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-[--color-text-3]">Actor ID</dt>
                  <dd className="font-mono text-[11px] text-[--color-text-2]">
                    {selected.actor_id}
                  </dd>
                </div>
                {selected.note && (
                  <div className="col-span-2">
                    <dt className="text-[--color-text-3]">Note</dt>
                    <dd>{selected.note}</dd>
                  </div>
                )}
              </dl>

              <AuditDiff before={selected.before_state} after={selected.after_state} />

              <button
                type="button"
                onClick={() => setShowRaw((v) => !v)}
                className="mt-4 text-[11px] text-[--color-text-3] underline underline-offset-2 hover:text-[--color-text-2]"
              >
                {showRaw ? "Hide raw JSON" : "Show raw JSON"}
              </button>
              {showRaw && (
                <div className="mt-2 grid gap-2">
                  <RawState label="Before" state={selected.before_state} />
                  <RawState label="After" state={selected.after_state} />
                </div>
              )}
            </DrawerBody>
          </DrawerContent>
        )}
      </Drawer>
    </>
  );
}

/** Humanized before→after diff; falls back to a note when nothing changed. */
function AuditDiff({
  before,
  after,
}: {
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}) {
  const lines = diffStates(before, after);
  return (
    <div className="mt-4">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[--color-text-3]">
        Changes
      </div>
      {lines.length === 0 ? (
        <div className="text-[12px] text-[--color-text-3]">No field changes recorded.</div>
      ) : (
        <dl className="grid gap-2">
          {lines.map((line) => (
            <div key={line.key} className="text-[12px]">
              <dt className="text-[--color-text-3]">{line.label}</dt>
              <dd className="flex items-center gap-2">
                <span className="text-[--color-text-2] line-through">{line.from}</span>
                <span className="text-[--color-text-3]">→</span>
                <span className="font-medium text-[--color-text-1]">{line.to}</span>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

/** Raw JSON snapshot for one state — the fallback expander view. */
function RawState({
  label,
  state,
}: {
  label: string;
  state: Record<string, unknown> | null;
}) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[--color-text-3]">
        {label}
      </div>
      <pre className="overflow-x-auto rounded border border-[--color-border] bg-[--color-surface-0] p-2 text-[11px] font-mono text-[--color-text-2]">
        {state ? JSON.stringify(state, null, 2) : "(none)"}
      </pre>
    </div>
  );
}
