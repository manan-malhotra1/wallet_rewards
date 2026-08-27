/**
 * <UnlockButton> — platform-admin button to release a user's PIN lockout
 * WITHOUT changing their PIN (distinct from Reset PIN). Only rendered when
 * the user is currently locked; a confirm dialog guards the action, matching
 * the Reset PIN affordance. On success it refreshes so the "Locked" pill clears.
 */
"use client";

import { LockOpen } from "lucide-react";
import * as React from "react";

import { unlockUserAction } from "@/app/(authenticated)/users/_actions";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ErrorBanner } from "@/components/ui/error-banner";
import { useToast } from "@/components/ui/toast";
import { heroActionButtonClass } from "./hero-action-button";

export function UnlockButton({
  userId,
  tenantId,
}: {
  userId: string;
  tenantId: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  // Clear transient state whenever the dialog closes.
  React.useEffect(() => {
    if (!open) {
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  const onConfirm = async () => {
    setSubmitting(true);
    setError(null);
    const result = await unlockUserAction(userId, tenantId);
    setSubmitting(false);
    if (result.ok) {
      setOpen(false);
      toast({ title: "User unlocked" });
    } else {
      setError(`${result.errorCode}: ${result.message}`);
    }
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        className={heroActionButtonClass}
      >
        <LockOpen className="h-3.5 w-3.5" />
        Unlock
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Unlock this user?</DialogTitle>
            <DialogDescription>
              This clears the PIN lockout so the user can try their PIN
              again immediately. It does NOT change the PIN — use Reset PIN
              if the user has forgotten it.
            </DialogDescription>
          </DialogHeader>
          {error && <ErrorBanner title="Couldn't unlock" description={error} />}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button onClick={onConfirm} disabled={submitting}>
              {submitting ? "Unlocking…" : "Unlock"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
