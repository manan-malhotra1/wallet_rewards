/**
 * <InstrumentsTable> — list with inline display_name + symbol edits,
 * status toggle, and soft-delete.
 */
"use client";

import { Check, Pencil, Trash2, X } from "lucide-react";
import * as React from "react";

import {
  deleteInstrumentAction,
  updateInstrumentAction,
} from "@/app/(authenticated)/instruments/_actions";
import { Button } from "@/components/ui/button";
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
import type { Instrument } from "@/lib/api-types";

const ACCOUNT_TYPE_LABEL: Record<Instrument["account_type"], string> = {
  financial_wallet: "Wallet",
  points_account: "Points",
};

export function InstrumentsTable({
  instruments,
  tenantId,
}: {
  instruments: Instrument[];
  tenantId: string;
}) {
  const [editingId, setEditingId] = React.useState<string | null>(null);
  const [editSymbol, setEditSymbol] = React.useState("");
  const [editName, setEditName] = React.useState("");
  const [pending, startTransition] = React.useTransition();
  const { toast } = useToast();

  function startEdit(inst: Instrument) {
    setEditingId(inst.id);
    setEditSymbol(inst.symbol);
    setEditName(inst.display_name);
  }

  function cancelEdit() {
    setEditingId(null);
  }

  function saveEdit(inst: Instrument) {
    startTransition(async () => {
      const res = await updateInstrumentAction(inst.id, tenantId, {
        symbol: editSymbol.trim(),
        display_name: editName.trim(),
      });
      if (res.ok) {
        toast({ title: "Instrument updated" });
        setEditingId(null);
      } else {
        toast({
          title: "Update failed",
          description: `${res.errorCode}: ${res.message}`,
        });
      }
    });
  }

  function toggleStatus(inst: Instrument) {
    const next = inst.status === "active" ? "disabled" : "active";
    startTransition(async () => {
      const res = await updateInstrumentAction(inst.id, tenantId, {
        status: next,
      });
      if (!res.ok) {
        toast({
          title: "Status update failed",
          description: `${res.errorCode}: ${res.message}`,
        });
      }
    });
  }

  function handleDelete(inst: Instrument) {
    if (
      !confirm(
        `Soft-delete instrument "${inst.code}"? It will disappear from dropdowns but existing ledger rows remain valid.`,
      )
    )
      return;
    startTransition(async () => {
      const res = await deleteInstrumentAction(inst.id, tenantId);
      if (res.ok) {
        toast({ title: "Instrument deleted" });
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
            <TableHeaderCell>Code</TableHeaderCell>
            <TableHeaderCell>Symbol</TableHeaderCell>
            <TableHeaderCell>Display name</TableHeaderCell>
            <TableHeaderCell>Account type</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell />
          </TableRow>
        </TableHead>
        <TableBody>
          {instruments.map((inst) => (
            <TableRow key={inst.id}>
              <TableCell className="font-mono text-[12px]">{inst.code}</TableCell>
              <TableCell>
                {editingId === inst.id ? (
                  <Input
                    value={editSymbol}
                    onChange={(e) => setEditSymbol(e.target.value)}
                    className="h-8 w-24"
                    maxLength={10}
                  />
                ) : (
                  <span className="font-medium">{inst.symbol}</span>
                )}
              </TableCell>
              <TableCell>
                {editingId === inst.id ? (
                  <Input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    className="h-8"
                  />
                ) : (
                  <span>{inst.display_name}</span>
                )}
              </TableCell>
              <TableCell className="text-[12px] text-[--color-text-3]">
                {ACCOUNT_TYPE_LABEL[inst.account_type]}
              </TableCell>
              <TableCell>
                <Select
                  value={inst.status}
                  onValueChange={() => toggleStatus(inst)}
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
                {editingId === inst.id ? (
                  <div className="flex justify-end gap-1">
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      onClick={() => saveEdit(inst)}
                      disabled={pending || !editName.trim() || !editSymbol.trim()}
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
                      onClick={() => startEdit(inst)}
                      aria-label="Edit"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      onClick={() => handleDelete(inst)}
                      aria-label="Delete"
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
