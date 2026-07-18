/**
 * <AccessLockControl> — platform-admin control (hero action row) to impose or
 * lift an admin access restriction: Lock login, Lock transactions, or Restore
 * access. Each choice is guarded by a confirm dialog (a login lock ends the
 * user's session) and calls setUserAccessAction. Distinct from the PIN-lockout
 * <UnlockButton>. Only the actions valid for the current level are rendered.
 */
"use client";

import { Ban, LockOpen, ShieldOff } from "lucide-react";
import * as React from "react";

import { setUserAccessAction } from "@/app/(authenticated)/users/_actions";
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
import type { AccessLevel, SettableAccessLevel } from "@/lib/api-types";

/** Per-target confirm-dialog copy and success toast, keyed by the level to set. */
const ACTION_COPY: Record<
  SettableAccessLevel,
  { label: string; title: string; description: string; toast: string }
> = {
  login_locked: {
    label: "Lock login",
    title: "Lock login for this user?",
    description:
      "This user will be unable to log in and any active session will be ended immediately. They can still be unlocked later.",
    toast: "Login locked",
  },
  transactions_locked: {
    label: "Lock transactions",
    title: "Lock transactions for this user?",
    description:
      "This user will be able to log in but unable to transact. Their session is not ended.",
    toast: "Transactions locked",
  },
  active: {
    label: "Restore access",
    title: "Restore access for this user?",
    description:
      "This user will regain full login and transaction access immediately.",
    toast: "Access restored",
  },
};

const ACTION_ICON: Record<
  SettableAccessLevel,
  React.ComponentType<{ className?: string }>
> = {
  login_locked: Ban,
  transactions_locked: ShieldOff,
  active: LockOpen,
};

/** The settable targets that make sense given the current access level. */
function availableTargets(level: AccessLevel): SettableAccessLevel[] {
  const all: SettableAccessLevel[] = [
    "login_locked",
    "transactions_locked",
    "active",
  ];
  return all.filter((target) => target !== level);
}

export function AccessLockControl({
  userId,
  tenantId,
  level,
}: {
  userId: string;
  tenantId: string;
  level: AccessLevel;
}) {
  const [target, setTarget] = React.useState<SettableAccessLevel | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  // Closed is a terminal state — no access-lock actions apply.
  if (level === "closed") return null;

  const onConfirm = async () => {
    if (!target) return;
    setSubmitting(true);
    setError(null);
    const result = await setUserAccessAction(userId, tenantId, target);
    setSubmitting(false);
    if (result.ok) {
      toast({ title: ACTION_COPY[target].toast });
      setTarget(null);
    } else {
      setError(`${result.errorCode}: ${result.message}`);
    }
  };

  const closeDialog = () => {
    if (submitting) return;
    setTarget(null);
    setError(null);
  };

  return (
    <>
      <div className="flex items-center gap-2">
        {availableTargets(level).map((t) => {
          const Icon = ACTION_ICON[t];
          return (
            <Button
              key={t}
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => {
                setError(null);
                setTarget(t);
              }}
            >
              <Icon className="h-3.5 w-3.5" />
              {ACTION_COPY[t].label}
            </Button>
          );
        })}
      </div>

      <Dialog open={target !== null} onOpenChange={(o) => !o && closeDialog()}>
        <DialogContent className="max-w-md">
          {target && (
            <>
              <DialogHeader>
                <DialogTitle>{ACTION_COPY[target].title}</DialogTitle>
                <DialogDescription>
                  {ACTION_COPY[target].description}
                </DialogDescription>
              </DialogHeader>
              {error && (
                <ErrorBanner title="Couldn't update access" description={error} />
              )}
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={closeDialog}
                  disabled={submitting}
                >
                  Cancel
                </Button>
                <Button onClick={onConfirm} disabled={submitting}>
                  {submitting ? "Applying…" : ACTION_COPY[target].label}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
