/**
 * <VerifyIdentifierButton> — admin affordance to manually verify an unverified
 * account_number identifier (Epic 27, Story 27.3).
 *
 * A small button rendered only on unverified account_number rows for
 * platform-admins. Clicking calls `verifyIdentifierAction`; on success it
 * toasts and refreshes so the row flips to a green Verified badge. Errors
 * surface inline beneath the row.
 */
"use client";

import { ShieldCheck } from "lucide-react";
import * as React from "react";
import { useRouter } from "next/navigation";

import { verifyIdentifierAction } from "@/app/(authenticated)/users/_actions";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";

export function VerifyIdentifierButton({
  userId,
  identifierId,
  tenantId,
}: {
  userId: string;
  identifierId: string;
  tenantId: string;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const onVerify = async () => {
    setError(null);
    setSubmitting(true);
    const result = await verifyIdentifierAction(userId, identifierId, tenantId);
    setSubmitting(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    toast({ title: "Identifier verified" });
    // Reflect the now-verified badge in the server-rendered detail card.
    router.refresh();
  };

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant="outline"
        size="sm"
        onClick={onVerify}
        disabled={submitting}
        className="gap-1.5"
      >
        <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
        {submitting ? "Verifying…" : "Verify"}
      </Button>
      {error && <p className="text-[11px] text-destructive">{error}</p>}
    </div>
  );
}
