/**
 * <WalletLimitsTable> — per-(tenant, currency) financial-wallet limits:
 * a max-balance ceiling + cumulative send/receive caps (daily/weekly/monthly).
 * Deleting PROPOSES a delete through the maker-checker pipeline; the row is
 * removed only once a second admin approves. Create through the dialog.
 */
"use client";

import { Pencil, Trash2 } from "lucide-react";
import * as React from "react";

import { ConfigViewButton } from "@/app/(authenticated)/_components/config-view-button";
import { proposeWalletLimitDeleteAction } from "@/app/(authenticated)/limits/_actions";
import { UserTypeBadge } from "@/app/(authenticated)/users/_components/user-type-badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { Tooltip } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";
import type { Instrument, WalletLimitConfig } from "@/lib/api-types";

import { CreateWalletLimitDialog } from "./create-wallet-limit-dialog";

const WINDOWS = [
  ["D", "daily"],
  ["W", "weekly"],
  ["M", "monthly"],
] as const;

/** Compact one-line "D 5×/1000 · W —/5000" summary for one direction's caps. */
function capsSummary(cfg: WalletLimitConfig, dir: "send" | "receive"): string {
  const parts: string[] = [];
  for (const [short, win] of WINDOWS) {
    const count = cfg[`${dir}_${win}_count_cap` as keyof WalletLimitConfig];
    const value = cfg[`${dir}_${win}_value_cap` as keyof WalletLimitConfig];
    if (count != null || value != null) {
      parts.push(`${short} ${count ?? "—"}× / ${value ?? "—"}`);
    }
  }
  return parts.length ? parts.join("  ·  ") : "—";
}

/**
 * Per-row Edit affordance — opens the create dialog in edit mode (proposes an
 * `update`). Self-contained so it composes with a tooltip.
 */
function EditWalletLimitButton({
  cfg,
  tenantId,
  instruments,
}: {
  cfg: WalletLimitConfig;
  tenantId: string;
  instruments: Instrument[];
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Tooltip content="Edit">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Edit wallet limit"
          onClick={() => setOpen(true)}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      </Tooltip>
      <CreateWalletLimitDialog
        tenantId={tenantId}
        instruments={instruments}
        editConfig={cfg}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}

export function WalletLimitsTable({
  configs,
  tenantId,
  instruments,
  canPropose,
}: {
  configs: WalletLimitConfig[];
  tenantId: string;
  /** Financial-wallet instruments offered when editing (currency is locked). */
  instruments: Instrument[];
  /** platform-admin gate — hides the Edit affordance for other admins. */
  canPropose: boolean;
}) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  const onDelete = async (id: string) => {
    setPending(id);
    const result = await proposeWalletLimitDeleteAction(id, tenantId);
    setPending(null);
    if (result.ok) {
      toast({ title: "Delete proposed — pending approval" });
    } else {
      toast({
        title: "Couldn't propose delete",
        description: `${result.errorCode}: ${result.message}`,
        variant: "danger",
      });
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell>User type</TableHeaderCell>
            <TableHeaderCell className="text-right">Max balance</TableHeaderCell>
            <TableHeaderCell>Send caps (count / value)</TableHeaderCell>
            <TableHeaderCell>Receive caps (count / value)</TableHeaderCell>
            <TableHeaderCell className="w-[120px] text-right"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {configs.map((cfg) => (
            <TableRow key={cfg.id}>
              <TableCell className="font-mono text-xs">{cfg.currency}</TableCell>
              <TableCell>
                {cfg.user_type ? (
                  <UserTypeBadge type={cfg.user_type} />
                ) : (
                  <span className="text-xs text-muted-foreground">All types</span>
                )}
              </TableCell>
              <TableCell className="text-right font-mono">
                {cfg.max_balance ?? "—"}
              </TableCell>
              <TableCell className="font-mono text-[11px] text-muted-foreground">
                {capsSummary(cfg, "send")}
              </TableCell>
              <TableCell className="font-mono text-[11px] text-muted-foreground">
                {capsSummary(cfg, "receive")}
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-1">
                  <ConfigViewButton
                    configType="wallet_limit"
                    data={cfg as unknown as Record<string, unknown>}
                    title={`Wallet limit · ${cfg.currency}`}
                  />
                  {canPropose && (
                    <EditWalletLimitButton
                      cfg={cfg}
                      tenantId={tenantId}
                      instruments={instruments}
                    />
                  )}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Propose delete of wallet limit"
                    disabled={pending === cfg.id}
                    onClick={() => onDelete(cfg.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
