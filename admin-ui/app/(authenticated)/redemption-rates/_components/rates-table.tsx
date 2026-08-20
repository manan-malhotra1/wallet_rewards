/**
 * <RatesTable> — every points→fiat conversion rate in the active tenant.
 *
 * Edit / Delete PROPOSE a change through the maker-checker pipeline. A rate
 * whose currency already has an open proposal shows "Active · change proposed"
 * and its Edit / Delete are disabled until that proposal resolves.
 */
"use client";

import { Pencil, Trash2 } from "lucide-react";
import * as React from "react";

import { ChangeProposedTooltip } from "@/app/(authenticated)/_components/change-proposed-tooltip";
import { ConfigStatusPill } from "@/app/(authenticated)/_components/config-status-pill";
import { ConfigViewButton } from "@/app/(authenticated)/_components/config-view-button";
import { proposeConversionRateDeleteAction } from "@/app/(authenticated)/redemption-rates/_actions";
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
import type { PointsConversionRate } from "@/lib/api-types";
import { configScopeKey } from "@/lib/config-scope";

import { CreateRateDialog } from "./create-rate-dialog";

/** "100 PTS = R10.00"-style cell text (plain numbers, currency labelled). */
function rateLabel(rate: PointsConversionRate): string {
  return `${Number(rate.points_per_unit)} PTS = ${Number(rate.value_per_unit).toFixed(2)} ${rate.currency}`;
}

/** Per-row Edit affordance — opens the dialog in edit mode (proposes `update`). */
function EditRateButton({
  rate,
  tenantId,
  changeProposed,
  currencies,
}: {
  rate: PointsConversionRate;
  tenantId: string;
  /** Open request on this currency → disable Edit until it resolves. */
  changeProposed: boolean;
  /** The tenant's financial currencies (the dialog's dropdown options). */
  currencies: string[];
}) {
  const [open, setOpen] = React.useState(false);
  if (changeProposed) {
    return (
      <ChangeProposedTooltip>
        <Button variant="ghost" size="icon-sm" aria-label="Edit rate" disabled>
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      </ChangeProposedTooltip>
    );
  }
  return (
    <>
      <Tooltip content="Edit">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Edit rate"
          onClick={() => setOpen(true)}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
      </Tooltip>
      <CreateRateDialog
        tenantId={tenantId}
        editRate={rate}
        currencies={currencies}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}

export function RatesTable({
  rates,
  tenantId,
  canPropose,
  changeProposedKeys,
  currencies,
}: {
  rates: PointsConversionRate[];
  tenantId: string;
  /** The tenant's financial currencies — the edit dialog's dropdown options. */
  currencies: string[];
  /** platform-admin gate — hides the Edit/Delete affordances for other admins. */
  canPropose: boolean;
  /** Scope keys with an open update/delete request → "change proposed" status. */
  changeProposedKeys: ReadonlySet<string>;
}) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  const onDelete = async (id: string) => {
    setPending(id);
    const result = await proposeConversionRateDeleteAction(id, tenantId);
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
    <div className="glass-panel overflow-hidden rounded-lg">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Currency</TableHeaderCell>
            <TableHeaderCell>Rate</TableHeaderCell>
            <TableHeaderCell className="text-right">Max points / txn</TableHeaderCell>
            <TableHeaderCell className="text-right">Max % of balance / txn</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell className="w-[120px] text-right"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rates.map((r) => {
            const changeProposed = changeProposedKeys.has(
              configScopeKey("conversion_rate", r as unknown as Record<string, unknown>),
            );
            return (
              <TableRow key={r.id}>
                <TableCell className="font-mono text-xs font-medium">{r.currency}</TableCell>
                <TableCell className="font-mono tabular-nums text-sm">{rateLabel(r)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {r.max_points_per_txn != null ? Number(r.max_points_per_txn) : "—"}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {r.max_balance_pct_per_txn != null
                    ? `${Number(r.max_balance_pct_per_txn)}%`
                    : "—"}
                </TableCell>
                <TableCell>
                  <ConfigStatusPill changeProposed={changeProposed} />
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-1">
                    <ConfigViewButton
                      configType="conversion_rate"
                      data={r as unknown as Record<string, unknown>}
                      title={`Conversion rate · ${r.currency}`}
                      tenantId={tenantId}
                      targetConfigId={r.id}
                      canPropose={canPropose}
                      changeProposed={changeProposed}
                    />
                    {canPropose && (
                      <EditRateButton
                        rate={r}
                        tenantId={tenantId}
                        changeProposed={changeProposed}
                        currencies={currencies}
                      />
                    )}
                    {canPropose &&
                      (changeProposed ? (
                        <ChangeProposedTooltip>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label="Propose delete of rate"
                            disabled
                          >
                            <Trash2 className="h-3.5 w-3.5 text-destructive" />
                          </Button>
                        </ChangeProposedTooltip>
                      ) : (
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label="Propose delete of rate"
                          disabled={pending === r.id}
                          onClick={() => onDelete(r.id)}
                        >
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      ))}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
