/**
 * <AuditTable> — rendered list of audit entries; clicking a row opens a
 * <Drawer> with the before/after JSON snapshots.
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
import { formatTimestamp, shortId } from "@/lib/utils";

import type { AuditEntry } from "@/lib/api-types";

function actorBadgeTone(actorType: AuditEntry["actor_type"]) {
  if (actorType === "admin") return "brand" as const;
  if (actorType === "user") return "accent" as const;
  return "neutral" as const;
}

export function AuditTable({ entries }: { entries: AuditEntry[] }) {
  const [selected, setSelected] = React.useState<AuditEntry | null>(null);

  return (
    <>
      <div className="overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface-1]">
        <Table>
          <TableHead>
            <TableRow>
              <TableHeaderCell className="w-[140px]">Time</TableHeaderCell>
              <TableHeaderCell>Actor</TableHeaderCell>
              <TableHeaderCell>Action</TableHeaderCell>
              <TableHeaderCell>Entity</TableHeaderCell>
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
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Badge tone={actorBadgeTone(entry.actor_type)}>
                      {entry.actor_type}
                    </Badge>
                    <span className="font-mono text-[11px] text-[--color-text-3]">
                      {entry.actor_id.length > 18
                        ? `${entry.actor_id.slice(0, 16)}…`
                        : entry.actor_id}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="font-mono text-[12px]">{entry.action}</TableCell>
                <TableCell>
                  <span className="text-[--color-text-2]">{entry.entity_type}</span>{" "}
                  <span className="font-mono text-[11px] text-[--color-text-3]">
                    {shortId(entry.entity_id)}
                  </span>
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
              <DrawerTitle>{selected.action}</DrawerTitle>
              <DrawerDescription>
                {selected.entity_type} · {shortId(selected.entity_id)} ·{" "}
                {formatTimestamp(selected.created_at)}
              </DrawerDescription>
            </DrawerHeader>
            <DrawerBody>
              <dl className="grid grid-cols-2 gap-3 text-[12px]">
                <div>
                  <dt className="text-[--color-text-3]">Actor</dt>
                  <dd className="font-mono">
                    {selected.actor_type} · {selected.actor_id}
                  </dd>
                </div>
                <div>
                  <dt className="text-[--color-text-3]">IP</dt>
                  <dd className="font-mono">{selected.ip_address ?? "—"}</dd>
                </div>
                {selected.note && (
                  <div className="col-span-2">
                    <dt className="text-[--color-text-3]">Note</dt>
                    <dd>{selected.note}</dd>
                  </div>
                )}
              </dl>
              <div className="mt-4">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[--color-text-3]">
                  Before
                </div>
                <pre className="overflow-x-auto rounded border border-[--color-border] bg-[--color-surface-0] p-2 text-[11px] font-mono text-[--color-text-2]">
                  {selected.before_state
                    ? JSON.stringify(selected.before_state, null, 2)
                    : "(none)"}
                </pre>
              </div>
              <div className="mt-3">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[--color-text-3]">
                  After
                </div>
                <pre className="overflow-x-auto rounded border border-[--color-border] bg-[--color-surface-0] p-2 text-[11px] font-mono text-[--color-text-2]">
                  {selected.after_state
                    ? JSON.stringify(selected.after_state, null, 2)
                    : "(none)"}
                </pre>
              </div>
            </DrawerBody>
          </DrawerContent>
        )}
      </Drawer>
    </>
  );
}
