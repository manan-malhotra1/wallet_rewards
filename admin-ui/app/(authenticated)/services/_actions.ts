"use server";

/**
 * Server actions for the Services catalog page.
 *
 * Wraps the backend CRUD on /api/v1/services and revalidates the page
 * on success so the catalog table and the consuming dropdowns refresh.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  createService,
  deleteService,
  updateService,
  type CreateServicePayload,
  type UpdateServicePayload,
} from "@/lib/api-endpoints";

export type ServiceActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

function revalidateAllConsumers() {
  revalidatePath("/services");
  revalidatePath("/limits");
  revalidatePath("/pricing");
  revalidatePath("/campaigns");
  revalidatePath("/rules");
}

export async function createServiceAction(
  payload: CreateServicePayload,
): Promise<ServiceActionResult> {
  try {
    await createService(payload);
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

export async function updateServiceAction(
  serviceId: string,
  tenantId: string,
  payload: UpdateServicePayload,
): Promise<ServiceActionResult> {
  try {
    await updateService(serviceId, tenantId, payload);
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

export async function deleteServiceAction(
  serviceId: string,
  tenantId: string,
): Promise<ServiceActionResult> {
  try {
    await deleteService(serviceId, tenantId);
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
