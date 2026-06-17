/**
 * <ResetPinButton> — admin button to generate a fresh PIN for a user.
 *
 * Today the new PIN is shown inline so the operator can read it back
 * to the user over a verified channel. Phase 2 swaps the inline reveal
 * for SMS delivery via the notifications module — at which point the
 * dialog will just confirm "SMS sent" without showing the PIN.
 */
"use client";

import { KeyRound } from "lucide-react";
import * as React from "react";

import { resetUserPinAction } from "@/app/(authenticated)/users/_actions";
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

type Stage = "confirm" | "result";

export function ResetPinButton({
  userId,
  tenantId,
}: {
  userId: string;
  tenantId: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [stage, setStage] = React.useState<Stage>("confirm");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [newPin, setNewPin] = React.useState<string | null>(null);
  const [deliveredVia, setDeliveredVia] = React.useState<"inline" | "sms">("inline");
  const { toast } = useToast();

  // Reset all transient state when the dialog closes.
  React.useEffect(() => {
    if (!open) {
      setStage("confirm");
      setError(null);
      setNewPin(null);
      setSubmitting(false);
    }
  }, [open]);

  const onConfirm = async () => {
    setSubmitting(true);
    setError(null);
    const result = await resetUserPinAction(userId, tenantId);
    setSubmitting(false);
    if (result.ok) {
      setDeliveredVia(result.deliveredVia);
      setNewPin(result.newPin);
      setStage("result");
      if (result.deliveredVia === "sms") {
        toast({ title: "PIN reset — SMS sent" });
      }
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
        className="gap-1.5"
      >
        <KeyRound className="h-3.5 w-3.5" />
        Reset PIN
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md">
          {stage === "confirm" ? (
            <>
              <DialogHeader>
                <DialogTitle>Reset this user's PIN?</DialogTitle>
                <DialogDescription>
                  A fresh 4-digit PIN will be generated and the user's old
                  PIN will stop working immediately. Today the new PIN is
                  shown here so you can read it back over a verified
                  channel; once the notifications module ships, it will
                  be SMS'd to the user instead.
                </DialogDescription>
              </DialogHeader>
              {error && (
                <ErrorBanner title="Couldn't reset" description={error} />
              )}
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => setOpen(false)}
                  disabled={submitting}
                >
                  Cancel
                </Button>
                <Button onClick={onConfirm} disabled={submitting}>
                  {submitting ? "Resetting…" : "Reset PIN"}
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>PIN reset</DialogTitle>
                <DialogDescription>
                  {deliveredVia === "sms"
                    ? "An SMS with the new PIN has been sent to the user."
                    : "Read this PIN back to the user over a verified channel. It will not be shown again."}
                </DialogDescription>
              </DialogHeader>
              {newPin && (
                <div className="rounded-lg border-2 border-dashed border-primary bg-primary/5 p-6 text-center">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    New PIN
                  </div>
                  <div className="mt-2 font-mono text-4xl font-bold tabular-nums tracking-[0.4em] text-primary">
                    {newPin}
                  </div>
                </div>
              )}
              <DialogFooter>
                <Button onClick={() => setOpen(false)}>Done</Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
