"use server";

/**
 * Server actions for the mobile-simulator. Wrap backend.ts so the
 * browser never touches PINs, session tokens, or HMAC secrets.
 */
import { revalidatePath } from "next/cache";

import {
  fireEventHttp,
  fireEventKafka,
  sendP2P,
} from "@/lib/backend";
import type { UserKey } from "@/lib/config";

export type ActionResult =
  | { ok: true; message: string }
  | { ok: false; message: string; needsPin?: boolean };

export async function sendP2PAction(
  sender: UserKey,
  recipient: UserKey,
  amount: string,
  pin?: string,
): Promise<ActionResult> {
  const parsed = Number(amount);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false, message: "Amount must be a positive number." };
  }
  const res = await sendP2P(sender, recipient, amount, pin);
  revalidatePath("/");
  if (res.ok) {
    return { ok: true, message: `Sent R ${amount} from ${sender} → ${recipient}.` };
  }
  // Surface the step-up flag so the UI can pop a PIN prompt without
  // parsing the error body itself.
  if (res.status === 401 && res.body.includes("step_up_required")) {
    return { ok: false, message: res.body, needsPin: true };
  }
  if (res.status === 401 && res.body.includes("invalid_step_up_pin")) {
    return { ok: false, message: "Incorrect PIN. Try again.", needsPin: true };
  }
  return { ok: false, message: `${res.status}: ${res.body}` };
}

export async function fireEventAction(
  user: UserKey,
  transactionType: string,
  amount: string,
  mode: "http" | "kafka",
): Promise<ActionResult> {
  const parsed = Number(amount);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false, message: "Amount must be a positive number." };
  }
  const fn = mode === "http" ? fireEventHttp : fireEventKafka;
  const res = await fn({ user, transactionType, amount });
  revalidatePath("/");
  if (res.ok) {
    return {
      ok: true,
      message: `${mode.toUpperCase()} ${transactionType} for ${user} — ${res.body}`,
    };
  }
  return { ok: false, message: `${res.status}: ${res.body}` };
}
