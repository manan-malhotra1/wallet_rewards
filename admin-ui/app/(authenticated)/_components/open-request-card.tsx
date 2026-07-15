/**
 * Open-request card — surfaces a maker's in-flight config proposal on the
 * config's native page (pricing / commission / tax / limits).
 *
 * Status-driven, one component reused across all four pages:
 *   - PENDING           → "Under approval" badge + proposed change.
 *   - CHANGES_REQUESTED → "Changes requested" badge + latest checker comment
 *                         + the maker's "Edit & resubmit" affordance.
 *
 * Every viewer sees the card (so anyone can tell a config is in flight) and can
 * open the version history read-only. Mutating affordances are maker-gated:
 * Withdraw and the `editAction` slot appear only to the maker on a non-terminal
 * request.
 */
"use client";

import { History } from "lucide-react";
import * as React from "react";

import { ConfigDetail } from "@/app/(authenticated)/_components/config-detail";
import {
  loadConfigRequestAction,
  withdrawConfigRequestAction,
} from "@/app/(authenticated)/config-requests/_actions";
import { RequestDetailDrawer } from "@/app/(authenticated)/config-requests/_components/request-detail-drawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import type { ConfigChangeRequest } from "@/lib/api-types";
import { formatTimestamp, shortId } from "@/lib/utils";

/** Non-terminal statuses can still be withdrawn / edited by the maker. */
function isNonTerminal(status: ConfigChangeRequest["status"]): boolean {
  return status === "PENDING" || status === "CHANGES_REQUESTED";
}

/** The most recent checker comment asking for changes (falls back to any comment). */
function latestComment(request: ConfigChangeRequest): string | null {
  const withComment = request.reviews.filter((r) => r.comment?.trim());
  if (withComment.length === 0) return null;
  const ordered = [...withComment].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at),
  );
  const changes = ordered.filter((r) => r.action === "changes_requested");
  const pick = (changes.length > 0 ? changes : ordered).at(-1);
  return pick?.comment ?? null;
}

export function OpenRequestCard({
  request,
  tenantId,
  currentAdminId,
  editAction,
  serviceNames,
}: {
  request: ConfigChangeRequest;
  tenantId: string;
  currentAdminId: string;
  /** The maker's edit affordance (revise dialog trigger); maker + CHANGES_REQUESTED only. */
  editAction?: React.ReactNode;
  /** `{ code: display_name }` so a service code renders as its friendly name. */
  serviceNames?: Record<string, string>;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = React.useState(false);
  // Version-history drawer state; detail is loaded on demand (revisions are
  // only returned by the single-request detail endpoint, not the list).
  const [detail, setDetail] = React.useState<ConfigChangeRequest | null>(null);
  const [drawerOpen, setDrawerOpen] = React.useState(false);

  const isPending = request.status === "PENDING";
  const isMaker = request.maker_admin_id === currentAdminId;
  const canWithdraw = isMaker && isNonTerminal(request.status);
  const comment = latestComment(request);

  const onWithdraw = async () => {
    if (
      !window.confirm(
        "Withdraw this proposed change? It will no longer be reviewed. You can propose it again later.",
      )
    ) {
      return;
    }
    setBusy(true);
    const result = await withdrawConfigRequestAction(tenantId, request.id);
    setBusy(false);
    if (result.ok) {
      toast({ title: "Request withdrawn" });
    } else {
      toast({
        title: "Couldn't withdraw",
        description: `${result.errorCode}: ${result.message}`,
        variant: "danger",
      });
    }
  };

  const onViewVersions = async () => {
    setBusy(true);
    const result = await loadConfigRequestAction(tenantId, request.id);
    setBusy(false);
    if (!result.ok) {
      toast({
        title: "Couldn't load versions",
        description: `${result.errorCode}: ${result.message}`,
        variant: "danger",
      });
      return;
    }
    setDetail(result.request);
    setDrawerOpen(true);
  };

  const accent = isPending
    ? "border-sky-500/40 bg-sky-500/5"
    : "border-amber-500/40 bg-amber-500/5";

  return (
    <div className={`rounded-lg border p-4 ${accent}`}>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <Badge variant={isPending ? "info" : "warning"}>
          {isPending ? "Under approval" : "Changes requested"}
        </Badge>
        <Badge variant="secondary">{request.operation}</Badge>
        <span className="text-muted-foreground">
          maker {request.maker_admin_name ?? shortId(request.maker_admin_id)}
        </span>
        <span className="text-muted-foreground">·</span>
        <span className="text-muted-foreground">
          {formatTimestamp(request.updated_at)}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={onViewVersions}
          >
            <History className="h-3.5 w-3.5" />
            View versions
          </Button>
          {editAction}
          {canWithdraw && (
            <Button
              variant="danger"
              size="sm"
              disabled={busy}
              onClick={onWithdraw}
            >
              Withdraw
            </Button>
          )}
        </div>
      </div>
      {comment && (
        <div className="mb-3 rounded-md border-l-2 border-amber-500/60 bg-background/50 px-3 py-2 text-sm text-foreground">
          <span className="text-xs font-medium text-muted-foreground">
            Checker:{" "}
          </span>
          {comment}
        </div>
      )}
      {request.operation === "delete" ? (
        <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
          <span className="text-muted-foreground">Removes config: </span>
          <span className="text-foreground">
            {request.target_config_id ? shortId(request.target_config_id) : "—"}
          </span>
        </div>
      ) : (
        <ConfigDetail
          configType={request.config_type}
          data={request.payload}
          serviceNames={serviceNames}
        />
      )}
      {detail && (
        <RequestDetailDrawer
          request={detail}
          tenantId={tenantId}
          // Read-only from the native page: approvals happen in the queue.
          canApprove={false}
          currentAdminId={currentAdminId}
          open={drawerOpen}
          onOpenChange={setDrawerOpen}
          onUpdated={(updated) => setDetail(updated)}
          serviceNames={serviceNames}
        />
      )}
    </div>
  );
}
