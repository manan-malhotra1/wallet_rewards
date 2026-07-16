/**
 * Open-request card — surfaces a maker's in-flight config proposal on the
 * config's native page (pricing / commission / tax / limits).
 *
 * Compact: one row with the vital identifiers (config-type + operation badges,
 * a resolved one-line scope summary, status, maker, timestamp) plus a "View"
 * affordance that opens the full read-only detail drawer. Full payload,
 * version history, and the review thread all live in that drawer — nothing is
 * lost by keeping the card itself terse.
 *
 * Status-driven, one component reused across all four config pages:
 *   - PENDING           → "Under approval" (sky accent).
 *   - CHANGES_REQUESTED → "Changes requested" (amber accent) + the latest
 *                         checker comment, truncated to one line.
 *
 * Every viewer sees the card (so anyone can tell a config is in flight) and can
 * open the detail drawer read-only. Mutating affordances are maker-gated:
 * Withdraw and the `editAction` slot appear only to the maker on a non-terminal
 * request.
 */
"use client";

import { Eye } from "lucide-react";
import * as React from "react";

import {
  loadConfigRequestAction,
  withdrawConfigRequestAction,
} from "@/app/(authenticated)/config-requests/_actions";
import { RequestDetailDrawer } from "@/app/(authenticated)/config-requests/_components/request-detail-drawer";
import { USER_TYPE_OPTIONS } from "@/app/(authenticated)/users/_components/user-type-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import { Tooltip } from "@/components/ui/tooltip";
import type { ConfigChangeRequest } from "@/lib/api-types";
import { serviceLabel } from "@/lib/service-label";
import { formatTimestamp, shortId } from "@/lib/utils";

/** `{ value: label }` for user-type codes, e.g. `agent` → "Agent". */
const USER_TYPE_LABEL: Record<string, string> = Object.fromEntries(
  USER_TYPE_OPTIONS.map((o) => [o.value, o.label]),
);

/** Non-terminal statuses can still be withdrawn / edited by the maker. */
function isNonTerminal(status: ConfigChangeRequest["status"]): boolean {
  return status === "PENDING" || status === "CHANGES_REQUESTED";
}

/**
 * One-line scope summary from the request payload, e.g. "Cash In · ZAR · Agent".
 * Currency-only config types (tax / wallet_limit) drop the service leg and read
 * as "ZAR" or "ZAR · Agent". Falls back to "—" when the payload is absent.
 */
function scopeSummary(
  request: ConfigChangeRequest,
  serviceNames?: Record<string, string>,
): string {
  const payload = request.payload;
  if (!payload) return "—";
  const bands = Array.isArray(payload.bands)
    ? (payload.bands as Array<Record<string, unknown>>)
    : null;
  const txnCode =
    (payload.transaction_type as string | undefined) ??
    (bands?.[0]?.transaction_type as string | undefined);
  const userType = payload.user_type as string | undefined;
  const parts: string[] = [];
  if (txnCode) parts.push(serviceLabel(txnCode, serviceNames));
  if (payload.currency) parts.push(String(payload.currency));
  if (userType) parts.push(USER_TYPE_LABEL[userType] ?? userType);
  return parts.length ? parts.join(" · ") : "—";
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
  // Detail drawer state; the full request (payload + revisions + review thread)
  // is loaded on demand — the list endpoint omits revisions.
  const [detail, setDetail] = React.useState<ConfigChangeRequest | null>(null);
  const [drawerOpen, setDrawerOpen] = React.useState(false);

  const isPending = request.status === "PENDING";
  const isMaker = request.maker_admin_id === currentAdminId;
  const canWithdraw = isMaker && isNonTerminal(request.status);
  const comment = !isPending ? latestComment(request) : null;

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

  const onViewDetail = async () => {
    setBusy(true);
    const result = await loadConfigRequestAction(tenantId, request.id);
    setBusy(false);
    if (!result.ok) {
      toast({
        title: "Couldn't load request",
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
    <div className={`rounded-lg border p-3 ${accent}`}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="info">{request.config_type}</Badge>
        <Badge variant="secondary">{request.operation}</Badge>
        {request.operation === "delete" ? (
          <span className="text-sm text-foreground">
            Removes{" "}
            {request.target_config_id
              ? shortId(request.target_config_id)
              : "config"}
          </span>
        ) : (
          <span className="text-sm text-foreground">
            {scopeSummary(request, serviceNames)}
          </span>
        )}
        {/* A brand-new create has no prior applied version — make it obvious the
            config isn't live yet and only becomes v1 once approved. */}
        {request.operation === "create" && (
          <Badge variant="outline">Not yet active — becomes v1 once approved</Badge>
        )}
        <StatusPill status={request.status} />
        <span className="text-muted-foreground">
          maker {request.maker_admin_name ?? shortId(request.maker_admin_id)}
        </span>
        <span className="text-muted-foreground">·</span>
        <span className="text-muted-foreground">
          {formatTimestamp(request.updated_at)}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <Tooltip content="View details">
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="View request details"
              disabled={busy}
              onClick={onViewDetail}
            >
              <Eye className="h-3.5 w-3.5" />
            </Button>
          </Tooltip>
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
        <p
          className="mt-2 truncate text-xs text-muted-foreground"
          title={comment}
        >
          <span className="font-medium">Checker: </span>
          {comment}
        </p>
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
