/**
 * <ServicesTable> — list every service, with inline display_name edit and
 * status toggle. Soft-delete is the trash icon at row end.
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
import type { Service } from "@/lib/api-types";

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
            <TableHeaderCell>Code</TableHeaderCell>
            <TableHeaderCell>Description</TableHeaderCell>
            <TableHeaderCell>Who can initiate</TableHeaderCell>
            <TableHeaderCell>Channels</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell />
          </TableRow>
        </TableHead>
        <TableBody>
          {services.map((svc) => (
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
                  <span className="font-medium">{svc.display_name}</span>
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
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      onClick={() => handleDelete(svc)}
                      aria-label="Delete service"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
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

// Keep Badge import available for future status pill variants.
export const _UnusedBadgeKeep = Badge;
