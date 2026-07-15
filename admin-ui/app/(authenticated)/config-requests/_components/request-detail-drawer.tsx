/**
 * Config-request detail drawer (Epic 24 / Story 24.3; Epic 25 / Task 7).
 *
 * Read-only view of the proposed change (rendered via the shared
 * `ConfigDetail` in sans typography) plus the review thread, with role-gated
 * actions:
 *   - Checker (config-approver, not the maker): Approve / Request changes.
 *   - Maker: Withdraw any non-terminal request.
 *
 * The maker no longer edits the payload here — form-based revise now happens on
 * the native config pages (Epic 25 / Task 9). No JSON editor, no mono font.
 */
"use client";

import * as React from "react";

import { ConfigDetail } from "@/app/(authenticated)/_components/config-detail";
import {
  approveConfigRequestAction,
  requestConfigChangesAction,
  withdrawConfigRequestAction,
} from "@/app/(authenticated)/config-requests/_actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Label } from "@/components/ui/label";
import { StatusPill } from "@/components/ui/status-pill";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { cn, formatTimestamp, shortId } from "@/lib/utils";
import type { ConfigChangeRequest } from "@/lib/api-types";

/** Non-terminal statuses can still be withdrawn / acted on. */
function isNonTerminal(status: ConfigChangeRequest["status"]): boolean {
  return status === "PENDING" || status === "CHANGES_REQUESTED";
}

/** The proposed change — a delete names its target; a create renders via ConfigDetail. */
function ProposedChange({ request }: { request: ConfigChangeRequest }) {
  if (request.operation === "delete") {
    return (
      <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
        <span className="text-muted-foreground">Target config: </span>
        <span className="text-foreground">
          {request.target_config_id ? shortId(request.target_config_id) : "—"}
        </span>
      </div>
    );
  }
  return <ConfigDetail configType={request.config_type} data={request.payload} />;
}

function ReviewThread({ request }: { request: ConfigChangeRequest }) {
  if (request.reviews.length === 0) {
    return <p className="text-sm text-muted-foreground">No reviews yet.</p>;
  }
  const ordered = [...request.reviews].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at),
  );
  return (
    <ol className="space-y-3">
      {ordered.map((review) => (
        <li key={review.id} className="border-l-2 border-border pl-3">
          <div className="flex items-center gap-2 text-xs">
            <Badge variant="outline">{review.action}</Badge>
            <span className="text-muted-foreground">{review.actor_role}</span>
            <span className="text-muted-foreground">·</span>
            <span className="text-muted-foreground">
              {review.actor_admin_name ?? shortId(review.actor_admin_id)}
            </span>
            <span className="ml-auto text-muted-foreground">
              {formatTimestamp(review.created_at)}
            </span>
          </div>
          {review.comment && (
            <p className="mt-1 text-sm text-foreground">{review.comment}</p>
          )}
        </li>
      ))}
    </ol>
  );
}

/**
 * Version history — a compact revision selector plus the selected revision's
 * payload rendered via `ConfigDetail`. Defaults to the latest revision. Only
 * meaningful for create ops (delete ops carry no payload); renders nothing when
 * the detail endpoint returned no revisions.
 */
function VersionHistory({ request }: { request: ConfigChangeRequest }) {
  const revisions = request.revisions ?? [];
  // Ascending by revision so the last entry is the latest.
  const ordered = React.useMemo(
    () => [...revisions].sort((a, b) => a.revision - b.revision),
    [revisions],
  );
  const [selected, setSelected] = React.useState<number | null>(null);

  // Reset to the latest revision whenever the drawer opens on a new request.
  React.useEffect(() => {
    setSelected(ordered.length > 0 ? ordered[ordered.length - 1].revision : null);
  }, [request.id, ordered]);

  if (request.operation === "delete" || ordered.length === 0) return null;

  const current = ordered.find((r) => r.revision === selected) ?? ordered[ordered.length - 1];

  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Versions
      </h3>
      <div className="mb-3 flex flex-wrap gap-1">
        {ordered.map((rev) => (
          <button
            key={rev.revision}
            type="button"
            onClick={() => setSelected(rev.revision)}
            title={formatTimestamp(rev.created_at)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs transition-colors",
              rev.revision === current.revision
                ? "bg-primary font-medium text-primary-foreground"
                : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
            )}
          >
            v{rev.revision}
          </button>
        ))}
      </div>
      <div className="mb-2 text-xs text-muted-foreground">
        Revision {current.revision} · {formatTimestamp(current.created_at)}
      </div>
      <ConfigDetail configType={request.config_type} data={current.payload} />
    </section>
  );
}

export function RequestDetailDrawer({
  request,
  tenantId,
  canApprove,
  currentAdminId,
  open,
  onOpenChange,
  onUpdated,
}: {
  request: ConfigChangeRequest;
  tenantId: string;
  canApprove: boolean;
  currentAdminId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (request: ConfigChangeRequest) => void;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  // Comment box for request-changes (mandatory comment).
  const [commentMode, setCommentMode] = React.useState(false);
  const [comment, setComment] = React.useState("");

  // Reset transient editors whenever the drawer opens on a new request.
  React.useEffect(() => {
    setCommentMode(false);
    setComment("");
    setErrorBanner(null);
  }, [request.id, open]);

  const isMaker = currentAdminId === request.maker_admin_id;
  const isChecker = canApprove && !isMaker;
  const nonTerminal = isNonTerminal(request.status);
  // Checkers act on requests awaiting their review.
  const canReview = isChecker && request.status === "PENDING";

  const run = async (
    label: string,
    fn: () => Promise<
      | { ok: true; request: ConfigChangeRequest }
      | { ok: false; errorCode: string; message: string }
    >,
  ) => {
    setErrorBanner(null);
    setBusy(true);
    const result = await fn();
    setBusy(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return false;
    }
    toast({ title: label });
    onUpdated(result.request);
    return true;
  };

  const onApprove = () =>
    run("Request approved", () =>
      approveConfigRequestAction(tenantId, request.id),
    );

  const onRequestChanges = async () => {
    if (!comment.trim()) {
      setErrorBanner("A comment is required when requesting changes.");
      return;
    }
    const ok = await run("Changes requested", () =>
      requestConfigChangesAction(tenantId, request.id, comment.trim()),
    );
    if (ok) setCommentMode(false);
  };

  const onWithdraw = () =>
    run("Request withdrawn", () =>
      withdrawConfigRequestAction(tenantId, request.id),
    );

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle className="flex items-center gap-2">
            <Badge variant="info">{request.config_type}</Badge>
            <Badge variant="secondary">{request.operation}</Badge>
            <StatusPill status={request.status} variant="full" />
          </DrawerTitle>
          <div className="text-xs text-muted-foreground">
            Revision {request.revision} · maker{" "}
            {request.maker_admin_name ?? shortId(request.maker_admin_id)} ·{" "}
            {formatTimestamp(request.created_at)}
          </div>
        </DrawerHeader>
        <DrawerBody className="space-y-6">
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Proposed change
            </h3>
            <ProposedChange request={request} />
          </section>
          <VersionHistory request={request} />
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Review thread
            </h3>
            <ReviewThread request={request} />
          </section>
          {commentMode && (
            <section className="space-y-2">
              <Label htmlFor="rc-comment">Comment (required)</Label>
              <Textarea
                id="rc-comment"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Explain what needs to change…"
              />
            </section>
          )}
          {errorBanner && (
            <ErrorBanner title="Action failed" description={errorBanner} />
          )}
        </DrawerBody>
        <DrawerFooter>
          {/* Checker actions */}
          {canReview && !commentMode && (
            <>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => setCommentMode(true)}
              >
                Request changes
              </Button>
              <Button disabled={busy} onClick={onApprove}>
                {busy ? "Working…" : "Approve"}
              </Button>
            </>
          )}
          {canReview && commentMode && (
            <>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => setCommentMode(false)}
              >
                Cancel
              </Button>
              <Button disabled={busy} onClick={onRequestChanges}>
                {busy ? "Working…" : "Submit comment"}
              </Button>
            </>
          )}
          {/* Maker action — form-based revise happens on the native pages. */}
          {isMaker && nonTerminal && (
            <Button variant="danger" disabled={busy} onClick={onWithdraw}>
              {busy ? "Working…" : "Withdraw"}
            </Button>
          )}
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  );
}
