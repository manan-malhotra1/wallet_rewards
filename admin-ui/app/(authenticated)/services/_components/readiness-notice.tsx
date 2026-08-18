/**
 * <ReadinessNotice> — flags a service that cannot transact yet, and why.
 *
 * A service row on its own moves no money: it also needs a pricing config, a
 * limit config, and a role granting its code. Without this notice an operator
 * meets each gap as a failed transaction (422 `pricing_config_missing`, or a
 * `NotAuthorised`) long after creating the service, with nothing on screen
 * connecting the error to the missing config.
 */
import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import type { ServiceReadiness } from "@/lib/api-types";
import {
  missingPrerequisites,
  type Prerequisite,
} from "@/lib/service-catalog";

/**
 * Where an operator goes to supply each prerequisite. `role` has no entry: the
 * admin UI has no roles screen yet, so role grants happen via the API. Saying
 * so is better than linking somewhere that can't fix it.
 */
const FIX_HREF: Partial<Record<Prerequisite, string>> = {
  pricing: "/pricing",
  limits: "/limits",
};

const LABELS: Record<Prerequisite, string> = {
  pricing: "pricing",
  limits: "limits",
  role: "role grant",
};

export function ReadinessNotice({
  readiness,
}: {
  readiness: ServiceReadiness | null;
}) {
  const missing = missingPrerequisites(readiness);
  if (missing.length === 0) return null;

  return (
    <div className="mt-1 flex flex-col gap-0.5">
      <Badge variant="warning" className="w-fit text-[10px]">
        Not yet usable
      </Badge>
      <span className="text-[10px] leading-tight text-[--color-text-3]">
        Needs{" "}
        {missing.map((key, i) => {
          const href = FIX_HREF[key];
          return (
            // Each label is its own element (never sharing a text node with the
            // separator) so it stays individually addressable.
            <React.Fragment key={key}>
              {i > 0 && <span aria-hidden="true"> · </span>}
              {href ? (
                <Link href={href} className="underline hover:no-underline">
                  {LABELS[key]}
                </Link>
              ) : (
                <span>{LABELS[key]}</span>
              )}
            </React.Fragment>
          );
        })}
      </span>
    </div>
  );
}
