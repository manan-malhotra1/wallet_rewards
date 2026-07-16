/**
 * <ConfigStatusPill> — per-row status for a live config (Epic 25 Pass 2).
 *
 * A live config row is normally "Active". When an OPEN (PENDING /
 * CHANGES_REQUESTED) update or delete request targets that row's scope, it
 * shows an amber "Active · change proposed" so operators can see at a glance
 * which configs have a pending change. The icon + text carry the meaning; the
 * colour is only a reinforcement (frontend-admin accessibility rule).
 */
import { CircleCheck, Clock } from "lucide-react";

import { Badge } from "@/components/ui/badge";

/**
 * @param changeProposed Whether an open update/delete request targets this
 *   row's scope. Compute via `changeProposedScopeKeys` on the page and test
 *   `set.has(configScopeKey(configType, row))`.
 */
export function ConfigStatusPill({ changeProposed }: { changeProposed: boolean }) {
  if (changeProposed) {
    return (
      <Badge variant="warning" className="gap-1">
        <Clock className="h-3 w-3" aria-hidden="true" />
        Active · change proposed
      </Badge>
    );
  }
  return (
    <Badge variant="success" className="gap-1">
      <CircleCheck className="h-3 w-3" aria-hidden="true" />
      Active
    </Badge>
  );
}
