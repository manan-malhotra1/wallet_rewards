"use server";

/**
 * Server actions for the Instruments catalog page.
 *
 * Wraps the backend CRUD on /api/v1/instruments and revalidates the
 * page on success so the catalog table and the consuming currency
 * dropdowns (Limits / Pricing) refresh.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  createInstrument,
  deleteInstrument,
  updateInstrument,
  type CreateInstrumentPayload,
  type UpdateInstrumentPayload,
} from "@/lib/api-endpoints";

export type InstrumentActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

function revalidateAllConsumers() {
  revalidatePath("/instruments");
  revalidatePath("/limits");
  revalidatePath("/pricing");
}

export async function createInstrumentAction(
  payload: CreateInstrumentPayload,
): Promise<InstrumentActionResult> {
  try {
    await createInstrument(payload);
    revalidateAllConsumers();
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiError) {
      return { ok: false, errorCode: err.errorCode, message: err.message };
    }
    return {
      ok: false,
      errorCode: "internal_error",
      message: err instanceof Error ? err.message : "Unknown error",
    };
  }
}

export async function updateInstrumentAction(
  instrumentId: string,
  tenantId: string,
  payload: UpdateInstrumentPayload,
): Promise<InstrumentActionResult> {
  try {
    await updateInstrument(instrumentId, tenantId, payload);
    revalidateAllConsumers();
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiError) {
      return { ok: false, errorCode: err.errorCode, message: err.message };
    }
    return {
      ok: false,
      errorCode: "internal_error",
      message: err instanceof Error ? err.message : "Unknown error",
    };
  }
}

export async function deleteInstrumentAction(
  instrumentId: string,
  tenantId: string,
): Promise<InstrumentActionResult> {
  try {
    await deleteInstrument(instrumentId, tenantId);
    revalidateAllConsumers();
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiError) {
      return { ok: false, errorCode: err.errorCode, message: err.message };
    }
    return {
      ok: false,
      errorCode: "internal_error",
      message: err instanceof Error ? err.message : "Unknown error",
    };
  }
}
