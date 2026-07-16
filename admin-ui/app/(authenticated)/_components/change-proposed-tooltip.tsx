/**
 * <ChangeProposedTooltip> — hover-help for a config affordance that is disabled
 * because the row's scope already has an OPEN change request (Epic 25 Pass 2).
 *
 * A config with a pending / changes-requested update or delete must not offer a
 * second Edit / Delete / restore — the maker resolves the in-flight request
 * first (the backend also rejects a duplicate). Wrap the DISABLED trigger button
 * so the tooltip still fires: a disabled `<button>` emits no pointer events, so
 * Radix needs a real element (the `<span>`) to hang the hover on.
 */
"use client";

import * as React from "react";

import { Tooltip } from "@/components/ui/tooltip";

/** Shared copy for every disabled "a change is already awaiting approval" affordance. */
export const CHANGE_PROPOSED_TOOLTIP =
  "A change is already awaiting approval — approve, reject, or withdraw it first.";

/**
 * Wrap a disabled affordance so it shows {@link CHANGE_PROPOSED_TOOLTIP} on hover.
 *
 * @param children The disabled trigger (e.g. a `<Button disabled>`).
 */
export function ChangeProposedTooltip({ children }: { children: React.ReactNode }) {
  return (
    <Tooltip content={CHANGE_PROPOSED_TOOLTIP}>
      <span className="inline-flex">{children}</span>
    </Tooltip>
  );
}
