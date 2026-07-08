/**
 * <ChangeTypeDialog> — change a user's type from the detail card (Epic 13).
 *
 * Confirm modal requiring a mandatory reason (recorded on the audit log).
 * Shows a parent field for agent/merchant target types. The backend enforces
 * parent compatibility (Decision D4) and platform-admin role, and is
 * idempotent by state, so re-submitting the same type is a safe no-op.
 */
"use client";

import * as React from "react";

import { changeUserTypeAction } from "@/app/(authenticated)/users/_actions";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import type { UserType } from "@/lib/api-types";

import { PARENT_REQUIRED_TYPES, USER_TYPE_OPTIONS } from "./user-type-badge";

export function ChangeTypeDialog({
  userId,
  tenantId,
  currentType,
  currentParentId,
}: {
  userId: string;
  tenantId: string;
  currentType: UserType;
  currentParentId: string | null;
}) {
  const { toast } = useToast();
  const [open, setOpen] = React.useState(false);
  const [newType, setNewType] = React.useState<UserType>(currentType);
  const [parentUserId, setParentUserId] = React.useState(currentParentId ?? "");
  const [reason, setReason] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) {
      setNewType(currentType);
      setParentUserId(currentParentId ?? "");
      setReason("");
      setErrorBanner(null);
    }
  }, [open, currentType, currentParentId]);

  const showParent = PARENT_REQUIRED_TYPES.includes(newType);

  const onSubmit = async () => {
    setErrorBanner(null);
    if (!reason.trim()) {
      setErrorBanner("A reason is required — it's recorded on the audit log.");
      return;
    }
    setSubmitting(true);
    const result = await changeUserTypeAction(userId, tenantId, {
      new_type: newType,
      parent_user_id: showParent ? parentUserId.trim() || null : null,
      reason: reason.trim(),
    });
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({ title: "User type changed", description: newType });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Change type
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change user type</DialogTitle>
          <DialogDescription>
            Requires platform-admin. The reason is recorded on the audit log.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className={showParent ? "grid grid-cols-2 gap-3" : ""}>
            <div>
              <Label htmlFor="newtype">New type</Label>
              <Select value={newType} onValueChange={(v) => setNewType(v as UserType)}>
                <SelectTrigger id="newtype">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {USER_TYPE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {showParent && (
              <div>
                <Label htmlFor="newparent">Parent user ID (optional)</Label>
                <Input
                  id="newparent"
                  value={parentUserId}
                  onChange={(e) => setParentUserId(e.target.value)}
                  placeholder="super_agent / head_merchant UUID"
                />
              </div>
            )}
          </div>
          <div>
            <Label htmlFor="reason">Reason</Label>
            <Input
              id="reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. onboarded as a retail agent"
            />
          </div>
          {errorBanner && <ErrorBanner title="Could not change type" description={errorBanner} />}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Saving…" : "Change type"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
