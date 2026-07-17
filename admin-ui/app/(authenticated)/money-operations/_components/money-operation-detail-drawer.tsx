/**
 * Money-operation detail drawer (Epic 18 — N-eyes maker-checker).
 *
 * Read-only view of the proposed treasury move (a friendly field list), the
 * N-eyes approval progress, and the review thread, with role-gated actions:
 *   - Checker (treasury-approver, not the maker): Approve / Request changes.
 *   - Maker: Withdraw any non-terminal operation.
 *   - Maker: Revise & resubmit while CHANGES_REQUESTED.
 *
 * Approve and Withdraw carry an inline confirm step (they move money / abandon
 * a proposal). Revise edits the payload as JSON — the backend re-validates it
 * against the operation's schema, so a bad edit fails safely with a 422.
 */
"use client";

import * as React from "react";

import {
  approveMoneyOperationAction,
  requestMoneyOpChangesAction,
  reviseAndResubmitMoneyOperationAction,
  withdrawMoneyOperationAction,
} from "@/app/(authenticated)/money-operations/_actions";
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
import { Money } from "@/components/ui/money";
import { StatusPill } from "@/components/ui/status-pill";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import type { MoneyOperation } from "@/lib/api-types";
import { moneyOperationLabel } from "@/lib/money-operation-label";
import { formatCap, formatTimestamp, shortId } from "@/lib/utils";

/** Non-terminal statuses can still be withdrawn / acted on. */
function isNonTerminal(status: MoneyOperation["status"]): boolean {
  return status === "PENDING" || status === "CHANGES_REQUESTED";
}

/**
 * N-eyes approval progress — "{n} of {N} approved" plus a dot per required
 * approval, filled as they come in. Exported so the table can reuse it inline.
 */
export function ApprovalProgress({ operation }: { operation: MoneyOperation }) {
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

/** Friendly labels for the payload keys across all four operations. */
const FIELD_LABEL: Record<string, string> = {
  identifier_type: "Identifier type",
  identifier_value: "Identifier",
  amount: "Amount",
  currency: "Currency",
  reason: "Reason",
  withdraw_all: "Withdraw all",
  bank_mirror_account_id: "Bank mirror",
  account_id: "System wallet",
  name: "Name",
};

/** The order fields render in per operation (only present keys are shown). */
const FIELD_ORDER = [
  "name",
  "identifier_type",
  "identifier_value",
  "account_id",
  "amount",
  "withdraw_all",
  "currency",
  "bank_mirror_account_id",
  "reason",
];

/** Render one payload value, formatting amounts and shortening account UUIDs. */
function FieldValue({
  op,
  fieldKey,
  value,
}: {
  op: MoneyOperation;
  fieldKey: string;
  value: unknown;
}) {
  if (fieldKey === "amount") {
    const currency = typeof op.payload.currency === "string" ? op.payload.currency : "";
    // adjust_system_wallet has no currency and a signed amount — show the sign.
    if (!currency) {
      const raw = Number(value ?? 0);
      return (
        <span className="font-mono text-sm tabular-nums">
          {raw >= 0 ? "+" : "−"}
          {formatCap(Math.abs(raw))}
        </span>
      );
    }
    return <Money amount={String(value)} currency={currency} />;
  }
  // The funded/withdrawn user — lead with the resolved name, keep the raw
  // identifier as a muted secondary line so it's still visible.
  if (fieldKey === "identifier_value" && op.subject_name) {
    return (
      <span className="text-sm text-foreground">
        {op.subject_name}
        <span className="ml-2 font-mono text-xs text-muted-foreground">{String(value)}</span>
      </span>
    );
  }
  // System-account / bank-mirror legs — show the resolved wallet name; fall
  // back to a shortened UUID only when the name couldn't be resolved.
  if (fieldKey === "account_id") {
    return op.account_name ? (
      <span className="text-sm text-foreground">{op.account_name}</span>
    ) : (
      <span className="font-mono text-xs">{shortId(String(value))}</span>
    );
  }
  if (fieldKey === "bank_mirror_account_id") {
    return op.bank_mirror_name ? (
      <span className="text-sm text-foreground">{op.bank_mirror_name}</span>
    ) : (
      <span className="font-mono text-xs">{shortId(String(value))}</span>
    );
  }
  if (fieldKey === "withdraw_all") {
    return <span className="text-sm">{value ? "Yes" : "No"}</span>;
  }
  return <span className="text-sm text-foreground">{String(value)}</span>;
}

/** A readable definition list of the proposed operation's payload. */
function ProposedOperation({ operation }: { operation: MoneyOperation }) {
  const entries = FIELD_ORDER.filter((key) => {
    const v = operation.payload[key];
    return v !== null && v !== undefined && v !== "";
  });
  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No payload fields.</p>;
  }
  return (
    <dl className="grid grid-cols-[minmax(120px,auto)_1fr] gap-x-4 gap-y-2 text-sm">
      {entries.map((key) => (
        <React.Fragment key={key}>
          <dt className="text-muted-foreground">{FIELD_LABEL[key] ?? key}</dt>
          <dd>
            <FieldValue op={operation} fieldKey={key} value={operation.payload[key]} />
          </dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function ReviewThread({ operation }: { operation: MoneyOperation }) {
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

export function MoneyOperationDetailDrawer({
  operation,
  tenantId,
  canApprove,
  currentAdminId,
  open,
  onOpenChange,
  onUpdated,
}: {
  operation: MoneyOperation;
  tenantId: string;
  canApprove: boolean;
  currentAdminId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (operation: MoneyOperation) => void;
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
      | { ok: true; operation: MoneyOperation }
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
      approveMoneyOperationAction(tenantId, operation.id),
    );

  const onWithdraw = () =>
    run("Operation withdrawn", () =>
      withdrawMoneyOperationAction(tenantId, operation.id),
    );

  const onRequestChanges = async () => {
    if (!comment.trim()) {
      setErrorBanner("A comment is required when requesting changes.");
      return;
    }
    await run("Changes requested", () =>
      requestMoneyOpChangesAction(tenantId, operation.id, comment.trim()),
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
      reviseAndResubmitMoneyOperationAction(tenantId, operation.id, parsed),
    );
  };

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle className="flex items-center gap-2">
            <Badge variant="info">{moneyOperationLabel(operation.operation)}</Badge>
            <StatusPill status={operation.status} variant="full" />
          </DrawerTitle>
          <div className="text-xs text-muted-foreground">
            maker {operation.maker_admin_name ?? shortId(operation.maker_admin_id)} ·{" "}
            {formatTimestamp(operation.created_at)}
            {operation.applied_transaction_id && (
              <>
                {" "}
                · txn {shortId(operation.applied_transaction_id)}
              </>
            )}
          </div>
        </DrawerHeader>
        <DrawerBody className="space-y-6">
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Proposed operation
            </h3>
            <ProposedOperation operation={operation} />
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
              <Label htmlFor="mo-comment">Comment (required)</Label>
              <Textarea
                id="mo-comment"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Explain what needs to change…"
              />
            </section>
          )}
          {mode === "revise" && (
            <section className="space-y-2">
              <Label htmlFor="mo-payload">Proposed payload (JSON)</Label>
              <Textarea
                id="mo-payload"
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
              description="Once the required approvals are reached it executes and moves money. This cannot be undone from here."
            />
          )}
          {mode === "confirm-withdraw" && (
            <ErrorBanner
              title="Withdraw this proposal?"
              description="The operation is abandoned and will not execute. This is terminal."
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
