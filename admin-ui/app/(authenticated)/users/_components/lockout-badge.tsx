/**
 * <LockoutBadge> — small red pill shown in the user hero while a user is
 * PIN-locked (5 failed attempts → 30-min auto-expiring lock). Renders a
 * human countdown derived from the remaining lockout TTL. Server component.
 */
import { Lock } from "lucide-react";

/** Render a remaining-lockout TTL (seconds) as a human "unlocks in Nm" hint. */
export function unlockCountdownLabel(unlocksInSeconds: number | null): string {
  if (unlocksInSeconds === null || unlocksInSeconds <= 0) return "unlocking…";
  const minutes = Math.ceil(unlocksInSeconds / 60);
  return minutes <= 1 ? "unlocks in <1m" : `unlocks in ${minutes}m`;
}

export function LockoutBadge({
  unlocksInSeconds,
}: {
  unlocksInSeconds: number | null;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-100">
      <Lock className="h-3 w-3" aria-hidden="true" />
      Locked
      <span className="font-normal text-red-200/90">
        · {unlockCountdownLabel(unlocksInSeconds)}
      </span>
    </span>
  );
}
