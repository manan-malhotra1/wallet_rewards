/**
 * <ServicesTable> — list every service, with inline display_name edit and
 * status toggle. Soft-delete is the trash icon at row end.
 *
 * Rows are grouped so each platform base service is followed by the derived
 * services running on it. That ordering is the point of the screen: a derived
 * service inherits its execution path from its base but NOT its pricing or
 * limits, so "what runs on p2p" is the question an operator actually needs
 * answered before changing anything.
 */
"use client";

import { Check, Pencil, ShieldCheck, Trash2, X } from "lucide-react";
import * as React from "react";

import {
  deleteServiceAction,
  updateServiceAction,
} from "@/app/(authenticated)/services/_actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EditServicePolicyDialog } from "./edit-policy-dialog";
import { PolicySummary } from "./policy-controls";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import type { Service } from "@/lib/api-types";

/**
 * Order rows as base-then-its-derived-children, each group alphabetical.
 *
 * Derived services whose base is missing from the list (soft-deleted, or
 * filtered out by a status query) are kept at the end rather than dropped —
 * they still exist and still transact, so hiding them would be worse than
 * showing them ungrouped.
 */
export function groupServices(services: Service[]): Service[] {
  const byName = (a: Service, b: Service) =>
    a.display_name.localeCompare(b.display_name);
  const bases = services.filter((s) => s.kind === "base").sort(byName);
  const derived = services.filter((s) => s.kind === "derived");
  const baseCodes = new Set(bases.map((b) => b.code));

  const ordered: Service[] = [];
  for (const base of bases) {
    ordered.push(base);
    ordered.push(
      ...derived.filter((d) => d.base_service_code === base.code).sort(byName),
    );
  }
  ordered.push(
    ...derived
      .filter((d) => !d.base_service_code || !baseCodes.has(d.base_service_code))
      .sort(byName),
  );
  return ordered;
}

export function ServicesTable({
  services,
  tenantId,
}: {
  services: Service[];
  tenantId: string;
}) {
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [editName, setEditName] = React.useState("");
  const [pending, startTransition] = React.useTransition();
  const { toast } = useToast();

  const rows = React.useMemo(() => groupServices(services), [services]);

  function startEdit(svc: Service) {
    setEditingId(svc.id);
    setEditName(svc.display_name);
  }

  function cancelEdit() {
    setEditingId(null);
  }

  function saveName(svc: Service) {
    startTransition(async () => {
      const res = await updateServiceAction(svc.id, tenantId, {
        display_name: editName.trim(),
      });
      if (res.ok) {
        toast({ title: "Service updated" });
        setEditingId(null);
      } else {
        toast({
          title: "Update failed",
          description: `${res.errorCode}: ${res.message}`,
        });
      }
    });
  }

  function toggleStatus(svc: Service) {
    const next = svc.status === "active" ? "disabled" : "active";
    startTransition(async () => {
      const res = await updateServiceAction(svc.id, tenantId, { status: next });
      if (!res.ok) {
        toast({
          title: "Status update failed",
          description: `${res.errorCode}: ${res.message}`,
        });
      }
    });
  }

  function handleDelete(svc: Service) {
    if (
      !confirm(
        `Soft-delete service "${svc.code}"? It will disappear from dropdowns but existing configurations remain valid.`,
      )
    )
      return;
    startTransition(async () => {
      const res = await deleteServiceAction(svc.id, tenantId);
      if (res.ok) {
        toast({ title: "Service deleted" });
      } else {
        toast({
          title: "Delete failed",
          description: `${res.errorCode}: ${res.message}`,
        });
      }
    });
  }

  return (
    <div className="glass-panel overflow-hidden rounded-lg">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Display name</TableHeaderCell>
            <TableHeaderCell>Type</TableHeaderCell>
            <TableHeaderCell>Code</TableHeaderCell>
            <TableHeaderCell>Description</TableHeaderCell>
            <TableHeaderCell>Who can initiate</TableHeaderCell>
            <TableHeaderCell>Channels</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell />
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((svc) => (
            <TableRow key={svc.id}>
              <TableCell>
                {editingId === svc.id ? (
                  <Input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    className="h-8"
                    autoFocus
                  />
                ) : (
                  // Indent marks a derived row as belonging to the base above
                  // it; nowrap keeps every name on one line so the column
                  // stays aligned regardless of name length.
                  <span
                    className={cn(
                      "font-medium whitespace-nowrap",
                      svc.kind === "derived" && "pl-4",
                    )}
                  >
                    {svc.display_name}
                  </span>
                )}
              </TableCell>
              <TableCell>
                {svc.kind === "derived" ? (
                  <Badge variant="info" className="text-[10px]">
                    Derived
                  </Badge>
                ) : (
                  <Badge variant="secondary" className="text-[10px]">
                    Platform
                  </Badge>
                )}
              </TableCell>
              <TableCell className="font-mono text-[12px] text-[--color-text-3]">
                {svc.code}
              </TableCell>
              <TableCell className="text-[12px] text-[--color-text-3]">
                {svc.description ?? "—"}
              </TableCell>
              <TableCell>
                <PolicySummary values={svc.allowed_user_types} />
              </TableCell>
              <TableCell>
                <PolicySummary values={svc.allowed_channels} />
              </TableCell>
              <TableCell>
                <Select
                  value={svc.status}
                  onValueChange={() => toggleStatus(svc)}
                  disabled={pending}
                >
                  <SelectTrigger className="h-7 w-[110px] text-[12px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="active">active</SelectItem>
                    <SelectItem value="disabled">disabled</SelectItem>
                  </SelectContent>
                </Select>
              </TableCell>
              <TableCell className="text-right">
                {editingId === svc.id ? (
                  <div className="flex justify-end gap-1">
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      onClick={() => saveName(svc)}
                      disabled={pending || !editName.trim()}
                      aria-label="Save"
                    >
                      <Check className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      onClick={cancelEdit}
                      aria-label="Cancel"
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ) : (
                  <div className="flex justify-end gap-1">
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      onClick={() => startEdit(svc)}
                      aria-label="Edit display name"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <EditServicePolicyDialog
                      service={svc}
                      tenantId={tenantId}
                      trigger={
                        <Button
                          size="icon-xs"
                          variant="ghost"
                          aria-label="Edit access policy"
                        >
                          <ShieldCheck className="h-3.5 w-3.5" />
                        </Button>
                      }
                    />
                    {/* Base services ship with the platform: the backend
                        refuses to delete them (409 base_service_protected),
                        so don't offer an action that cannot succeed. */}
                    {svc.kind === "derived" && (
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        onClick={() => handleDelete(svc)}
                        aria-label="Delete service"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
