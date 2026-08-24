/**
 * User-operation detail drawer (Epic 3 — N-eyes maker-checker).
 *
 * Read-only view of the proposed create / edit user request (a friendly field
 * list with resolved names), the N-eyes approval progress, and the review
 * thread, with role-gated actions:
 *   - Checker (user-approver, not the maker): Approve / Request changes.
 *   - Maker: Withdraw any non-terminal operation.
 *   - Maker: Revise & resubmit while CHANGES_REQUESTED.
 *
 * Approve and Withdraw carry an inline confirm step. Revise edits the payload
 * as JSON — the backend re-validates it against the operation's schema, so a
 * bad edit fails safely with a 422.
 */
"use client";

import * as React from "react";

import {
  approveUserOperationAction,
  requestUserOpChangesAction,
  reviseAndResubmitUserOperationAction,
  withdrawUserOperationAction,
} from "@/app/(authenticated)/user-operations/_actions";
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
import type { UserOperation, UserTypeCatalog } from "@/lib/api-types";
import { userOperationLabel } from "@/lib/user-operation-label";
import { userTypeLabel } from "@/lib/user-type-catalog";
import { formatTimestamp, shortId } from "@/lib/utils";

/** Non-terminal statuses can still be withdrawn / acted on. */
function isNonTerminal(status: UserOperation["status"]): boolean {
  return status === "PENDING" || status === "CHANGES_REQUESTED";
}

/**
 * N-eyes approval progress — "{n} of {N} approved" plus a dot per required
 * approval, filled as they come in. Exported so the table can reuse it inline.
 */
export function ApprovalProgress({ operation }: { operation: UserOperation }) {
  const { approvals_count, required_approvals } = operation;
  return (
    <span className="inline-flex items-center gap-2">
      <span className="flex items-center gap-1" aria-hidden="true">
        {Array.from({ length: required_approvals }).map((_, i) => (
          <span
            key={i}
            className={
              i < approvals_count
                ? "block h-2 w-2 rounded-full bg-emerald-500"
                : "block h-2 w-2 rounded-full bg-muted-foreground/30"
            }
          />
        ))}
      </span>
      <span className="text-xs text-muted-foreground">
        {approvals_count} of {required_approvals} approved
      </span>
    </span>
  );
}

/** A labelled definition-list row. */
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-foreground">{children}</dd>
    </>
  );
}

/** Read a payload field as a display string, tolerating missing values. */
function str(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

/** Render the identifiers + profile + type of a proposed create_user. */
function CreatePayload({
  operation,
  catalog,
}: {
  operation: UserOperation;
  catalog: UserTypeCatalog | null;
}) {
  const p = operation.payload;
  const idents = Array.isArray(p.identifiers)
    ? (p.identifiers as { identifier_type?: string; identifier_value?: string }[])
    : [];
  const profile = (p.profile ?? {}) as Record<string, unknown>;
  const userType = str(p, "user_type") ?? "consumer";
  const name = [profile.first_name, profile.last_name]
    .filter(Boolean)
    .join(" ");
  return (
    <dl className="grid grid-cols-[minmax(120px,auto)_1fr] gap-x-4 gap-y-2 text-sm">
      <Row label="User type">
        <Badge variant="secondary">{userTypeLabel(catalog, userType)}</Badge>
      </Row>
      {name && <Row label="Name">{name}</Row>}
      {profile.date_of_birth ? (
        <Row label="Date of birth">{String(profile.date_of_birth)}</Row>
      ) : null}
      <Row label="Identifiers">
        <ul className="space-y-1">
          {idents.length === 0 ? (
            <li className="text-muted-foreground">None</li>
          ) : (
            idents.map((ident, i) => (
              <li key={i} className="flex items-center gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {ident.identifier_type ?? "identifier"}
                </span>
                <span className="font-mono text-xs">{ident.identifier_value}</span>
              </li>
            ))
          )}
        </ul>
      </Row>
    </dl>
  );
}

/** Render the target + the changed editable fields of a proposed update_user. */
function UpdatePayload({
  operation,
  catalog,
}: {
  operation: UserOperation;
  catalog: UserTypeCatalog | null;
}) {
  const p = operation.payload;
  const targetId = str(p, "target_user_id");
  const fields: { label: string; key: string; badge?: boolean }[] = [
    { label: "First name", key: "first_name" },
    { label: "Last name", key: "last_name" },
    { label: "Status", key: "status", badge: true },
    { label: "User type", key: "user_type", badge: true },
  ];
  const changed = fields.filter((f) => str(p, f.key) !== null);
  return (
    <dl className="grid grid-cols-[minmax(120px,auto)_1fr] gap-x-4 gap-y-2 text-sm">
      <Row label="Editing user">
        {operation.target_name ? (
          <span>
            {operation.target_name}
            {targetId && (
              <span className="ml-2 font-mono text-xs text-muted-foreground">
                {shortId(targetId, "usr")}
              </span>
            )}
          </span>
        ) : (
          <span className="font-mono text-xs">
            {targetId ? shortId(targetId, "usr") : "—"}
          </span>
        )}
      </Row>
      {changed.length === 0 ? (
        <Row label="Changes">
          <span className="text-muted-foreground">No editable fields set.</span>
        </Row>
      ) : (
        changed.map((f) => (
          <Row key={f.key} label={f.label}>
            {f.key === "user_type" ? (
              userTypeLabel(catalog, str(p, f.key) ?? "")
            ) : f.badge ? (
              <StatusPill status={(str(p, f.key) ?? "").toUpperCase()} variant="dense" />
            ) : (
              str(p, f.key)
            )}
          </Row>
        ))
      )}
    </dl>
  );
}

/** A readable view of the proposed operation's payload, per operation type. */
function ProposedOperation({
  operation,
  catalog,
}: {
  operation: UserOperation;
  catalog: UserTypeCatalog | null;
}) {
  if (operation.operation === "create_user") {
    return <CreatePayload operation={operation} catalog={catalog} />;
  }
  if (operation.operation === "update_user") {
    return <UpdatePayload operation={operation} catalog={catalog} />;
  }
  return <p className="text-sm text-muted-foreground">Unknown operation.</p>;
}

function ReviewThread({ operation }: { operation: UserOperation }) {
  if (operation.reviews.length === 0) {
    return <p className="text-sm text-muted-foreground">No reviews yet.</p>;
  }
  const ordered = [...operation.reviews].sort(
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

/** Which transient footer editor is open. */
type Mode = "none" | "confirm-approve" | "confirm-withdraw" | "changes" | "revise";

export function UserOperationDetailDrawer({
  operation,
  tenantId,
  canApprove,
  currentAdminId,
  catalog,
  open,
  onOpenChange,
  onUpdated,
}: {
  operation: UserOperation;
  tenantId: string;
  canApprove: boolean;
  currentAdminId: string;
  /** The tenant's user-type catalog, so a type reads by name, not by code. */
  catalog: UserTypeCatalog | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (operation: UserOperation) => void;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const [mode, setMode] = React.useState<Mode>("none");
  const [comment, setComment] = React.useState("");
  const [payloadDraft, setPayloadDraft] = React.useState("");

  // Reset transient editors whenever the drawer opens on a new operation.
  React.useEffect(() => {
    setMode("none");
    setComment("");
    setErrorBanner(null);
    setPayloadDraft(JSON.stringify(operation.payload, null, 2));
  }, [operation.id, open, operation.payload]);

  const isMaker = currentAdminId === operation.maker_admin_id;
  const isChecker = canApprove && !isMaker;
  const nonTerminal = isNonTerminal(operation.status);
  // Checkers act on operations awaiting their review.
  const canReview = isChecker && operation.status === "PENDING";
  // Makers revise only after changes were requested.
  const canRevise = isMaker && operation.status === "CHANGES_REQUESTED";

  const run = async (
    label: string,
    fn: () => Promise<
      | { ok: true; operation: UserOperation }
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
    onUpdated(result.operation);
    setMode("none");
    return true;
  };

  const onApprove = () =>
    run("Operation approved", () =>
      approveUserOperationAction(tenantId, operation.id),
    );

  const onWithdraw = () =>
    run("Operation withdrawn", () =>
      withdrawUserOperationAction(tenantId, operation.id),
    );

  const onRequestChanges = async () => {
    if (!comment.trim()) {
      setErrorBanner("A comment is required when requesting changes.");
      return;
    }
    await run("Changes requested", () =>
      requestUserOpChangesAction(tenantId, operation.id, comment.trim()),
    );
  };

  const onReviseResubmit = async () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(payloadDraft);
    } catch {
      setErrorBanner("Payload is not valid JSON.");
      return;
    }
    await run("Revised & resubmitted", () =>
      reviseAndResubmitUserOperationAction(tenantId, operation.id, parsed),
    );
  };

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle className="flex items-center gap-2">
            <Badge variant="info">{userOperationLabel(operation.operation)}</Badge>
            <StatusPill status={operation.status} variant="full" />
          </DrawerTitle>
          <div className="text-xs text-muted-foreground">
            maker {operation.maker_admin_name ?? shortId(operation.maker_admin_id)} ·{" "}
            {formatTimestamp(operation.created_at)}
            {operation.applied_user_id && (
              <> · user {shortId(operation.applied_user_id, "usr")}</>
            )}
          </div>
        </DrawerHeader>
        <DrawerBody className="space-y-6">
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Proposed operation
            </h3>
            <ProposedOperation operation={operation} catalog={catalog} />
          </section>
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Approval progress
            </h3>
            <ApprovalProgress operation={operation} />
          </section>
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Review thread
            </h3>
            <ReviewThread operation={operation} />
          </section>
          {mode === "changes" && (
            <section className="space-y-2">
              <Label htmlFor="uo-comment">Comment (required)</Label>
              <Textarea
                id="uo-comment"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Explain what needs to change…"
              />
            </section>
          )}
          {mode === "revise" && (
            <section className="space-y-2">
              <Label htmlFor="uo-payload">Proposed payload (JSON)</Label>
              <Textarea
                id="uo-payload"
                value={payloadDraft}
                onChange={(e) => setPayloadDraft(e.target.value)}
                className="min-h-[180px] font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">
                The backend re-validates this against the operation schema; an
                invalid edit is rejected without changing anything.
              </p>
            </section>
          )}
          {mode === "confirm-approve" && (
            <ErrorBanner
              title="Approve this operation?"
              description="Once the required approvals are reached it applies and the user is created / edited. This cannot be undone from here."
            />
          )}
          {mode === "confirm-withdraw" && (
            <ErrorBanner
              title="Withdraw this proposal?"
              description="The operation is abandoned and will not apply. This is terminal."
            />
          )}
          {errorBanner && (
            <ErrorBanner title="Action failed" description={errorBanner} />
          )}
        </DrawerBody>
        <DrawerFooter>
          {/* Checker: default actions */}
          {canReview && mode === "none" && (
            <>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => setMode("changes")}
              >
                Request changes
              </Button>
              <Button disabled={busy} onClick={() => setMode("confirm-approve")}>
                Approve
              </Button>
            </>
          )}
          {/* Checker: request-changes comment step */}
          {canReview && mode === "changes" && (
            <>
              <Button variant="ghost" disabled={busy} onClick={() => setMode("none")}>
                Cancel
              </Button>
              <Button disabled={busy} onClick={onRequestChanges}>
                {busy ? "Working…" : "Submit comment"}
              </Button>
            </>
          )}
          {/* Checker: approve confirm step */}
          {canReview && mode === "confirm-approve" && (
            <>
              <Button variant="ghost" disabled={busy} onClick={() => setMode("none")}>
                Cancel
              </Button>
              <Button disabled={busy} onClick={onApprove}>
                {busy ? "Working…" : "Confirm approve"}
              </Button>
            </>
          )}
          {/* Maker: revise & resubmit */}
          {canRevise && mode === "none" && (
            <Button disabled={busy} onClick={() => setMode("revise")}>
              Revise & resubmit
            </Button>
          )}
          {canRevise && mode === "revise" && (
            <>
              <Button variant="ghost" disabled={busy} onClick={() => setMode("none")}>
                Cancel
              </Button>
              <Button disabled={busy} onClick={onReviseResubmit}>
                {busy ? "Working…" : "Revise & resubmit"}
              </Button>
            </>
          )}
          {/* Maker: withdraw (any non-terminal) */}
          {isMaker && nonTerminal && mode === "none" && (
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => setMode("confirm-withdraw")}
            >
              Withdraw
            </Button>
          )}
          {isMaker && mode === "confirm-withdraw" && (
            <>
              <Button variant="ghost" disabled={busy} onClick={() => setMode("none")}>
                Cancel
              </Button>
              <Button variant="danger" disabled={busy} onClick={onWithdraw}>
                {busy ? "Working…" : "Confirm withdraw"}
              </Button>
            </>
          )}
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  );
}
