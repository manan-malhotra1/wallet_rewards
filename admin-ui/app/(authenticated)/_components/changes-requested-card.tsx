/**
 * "Changes requested" card (Epic 25 / Task 9). Surfaces a maker's proposal that
 * a checker sent back, on the config's native page: the proposed change
 * (rendered via `ConfigDetail`), the checker's latest comment, and an action
 * slot (the "Edit & resubmit" dialog trigger, shown to the maker only).
 */
"use client";

import * as React from "react";

import { ConfigDetail } from "@/app/(authenticated)/_components/config-detail";
import { Badge } from "@/components/ui/badge";
import type { ConfigChangeRequest } from "@/lib/api-types";
import { formatTimestamp, shortId } from "@/lib/utils";

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

export function ChangesRequestedCard({
  request,
  action,
}: {
  request: ConfigChangeRequest;
  /** The maker's edit affordance (dialog trigger); omitted for non-makers. */
  action?: React.ReactNode;
}) {
  const comment = latestComment(request);
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="warning">Changes requested</Badge>
        <Badge variant="secondary">{request.operation}</Badge>
        <span className="text-muted-foreground">
          maker {request.maker_admin_name ?? shortId(request.maker_admin_id)}
        </span>
        <span className="text-muted-foreground">·</span>
        <span className="text-muted-foreground">
          {formatTimestamp(request.updated_at)}
        </span>
        {action && <div className="ml-auto">{action}</div>}
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
        <ConfigDetail configType={request.config_type} data={request.payload} />
      )}
    </div>
  );
}
