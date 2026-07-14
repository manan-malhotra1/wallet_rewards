/**
 * Config-request detail drawer (Epic 24 / Story 24.3). Renders the proposed
 * payload, the review thread, and role-gated actions:
 *   - Checker (config-approver, not the maker): Approve / Request changes.
 *   - Maker (while CHANGES_REQUESTED): Revise payload → Resubmit; Withdraw
 *     any non-terminal request.
 */
"use client";

import * as React from "react";

import {
  approveConfigRequestAction,
  requestConfigChangesAction,
  resubmitConfigRequestAction,
  reviseConfigRequestAction,
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
import type { ConfigChangeRequest } from "@/lib/api-types";
import { formatTimestamp, shortId } from "@/lib/utils";

/** Non-terminal statuses can still be withdrawn / acted on. */
function isNonTerminal(status: ConfigChangeRequest["status"]): boolean {
  return status === "PENDING" || status === "CHANGES_REQUESTED";
}

/** Render one payload value readably (objects fall back to JSON). */
function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function PayloadView({ request }: { request: ConfigChangeRequest }) {
  if (request.operation === "delete") {
    return (
      <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
        <span className="text-muted-foreground">Target config: </span>
        <span className="font-mono text-xs text-foreground">
          {request.target_config_id ?? "—"}
        </span>
      </div>
    );
  }
  const entries = Object.entries(request.payload ?? {});
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No payload.</p>;
  }
  return (
    <dl className="grid grid-cols-[minmax(0,10rem)_1fr] gap-x-3 gap-y-1.5 text-sm">
      {entries.map(([key, value]) => (
        <React.Fragment key={key}>
          <dt className="font-mono text-xs text-muted-foreground">{key}</dt>
          <dd className="font-mono text-xs text-foreground break-all">
            {renderValue(value)}
          </dd>
        </React.Fragment>
      ))}
    </dl>
  );
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
            <span className="font-mono text-muted-foreground">
              {shortId(review.actor_admin_id)}
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
  // Comment box for request-changes; payload editor for revise.
  const [commentMode, setCommentMode] = React.useState(false);
  const [comment, setComment] = React.useState("");
  const [reviseMode, setReviseMode] = React.useState(false);
  const [payloadText, setPayloadText] = React.useState("");

  // Reset transient editors whenever the drawer opens on a new request.
  React.useEffect(() => {
    setCommentMode(false);
    setComment("");
    setReviseMode(false);
    setPayloadText(JSON.stringify(request.payload ?? {}, null, 2));
    setErrorBanner(null);
  }, [request.id, request.payload, open]);

  const isMaker = currentAdminId === request.maker_admin_id;
  const isChecker = canApprove && !isMaker;
  const nonTerminal = isNonTerminal(request.status);
  // Checkers act on requests awaiting their review.
  const canReview = isChecker && request.status === "PENDING";
  // Makers resubmit after changes were requested (create OR delete).
  const canResubmit = isMaker && request.status === "CHANGES_REQUESTED";
  // Revise edits a payload — only create proposals have one. Delete
  // proposals carry no payload, so the backend rejects a revise (422
  // config_request_not_editable); hide the affordance for them.
  const canRevise = canResubmit && request.operation === "create";

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

  const onRevise = async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(payloadText);
    } catch {
      setErrorBanner("Payload must be valid JSON.");
      return;
    }
    // Must be a plain JSON object — arrays / scalars aren't valid payloads.
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      setErrorBanner("Payload must be a JSON object.");
      return;
    }
    const ok = await run("Payload revised", () =>
      reviseConfigRequestAction(
        tenantId,
        request.id,
        parsed as Record<string, unknown>,
      ),
    );
    if (ok) setReviseMode(false);
  };

  const onResubmit = () =>
    run("Resubmitted for approval", () =>
      resubmitConfigRequestAction(tenantId, request.id),
    );

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
            <span className="font-mono">{shortId(request.maker_admin_id)}</span>{" "}
            · {formatTimestamp(request.created_at)}
          </div>
        </DrawerHeader>
        <DrawerBody className="space-y-6">
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Proposed change
            </h3>
            {reviseMode ? (
              <div className="space-y-2">
                <Label htmlFor="payload-edit">Payload (JSON)</Label>
                <Textarea
                  id="payload-edit"
                  value={payloadText}
                  onChange={(e) => setPayloadText(e.target.value)}
                  className="min-h-[180px] font-mono text-xs"
                />
              </div>
            ) : (
              <PayloadView request={request} />
            )}
          </section>
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
          {/* Maker actions */}
          {canRevise && !reviseMode && (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => setReviseMode(true)}
            >
              Revise payload
            </Button>
          )}
          {canRevise && reviseMode && (
            <>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => setReviseMode(false)}
              >
                Cancel
              </Button>
              <Button disabled={busy} onClick={onRevise}>
                {busy ? "Saving…" : "Save payload"}
              </Button>
            </>
          )}
          {canResubmit && !reviseMode && (
            <Button disabled={busy} onClick={onResubmit}>
              {busy ? "Working…" : "Resubmit"}
            </Button>
          )}
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
