/**
 * Server actions for the Config-requests review screen (Epic 24 / Story
 * 24.3). Thin wrappers over the maker-checker endpoints; each returns the
 * updated request so the drawer can refresh in place, and revalidates the
 * review list + affected config pages.
 */
"use server";

import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  approveConfigRequest,
  getConfigRequest,
  requestConfigChanges,
  resubmitConfigRequest,
  reviseConfigRequest,
  withdrawConfigRequest,
} from "@/lib/api-endpoints";
import type { ConfigChangeRequest } from "@/lib/api-types";

export type ConfigRequestActionResult =
  | { ok: true; request: ConfigChangeRequest }
  | { ok: false; errorCode: string; message: string };

/** Config pages whose data may change once a request is applied. */
const CONFIG_PATHS = ["/pricing", "/commissions", "/taxes", "/limits"];

function revalidateAll() {
  revalidatePath("/config-requests");
  for (const path of CONFIG_PATHS) revalidatePath(path);
}

/** Fetch a single request with its full review thread (drawer detail). */
export async function loadConfigRequestAction(
  tenantId: string,
  id: string,
): Promise<ConfigRequestActionResult> {
  try {
    const request = await getConfigRequest(tenantId, id);
    return { ok: true, request };
  } catch (err) {
    return toResult(err);
  }
}

/** Approve a request (config-approver, must differ from the maker). */
export async function approveConfigRequestAction(
  tenantId: string,
  id: string,
): Promise<ConfigRequestActionResult> {
  try {
    const request = await approveConfigRequest(tenantId, id);
    revalidateAll();
    return { ok: true, request };
  } catch (err) {
    return toResult(err);
  }
}

/** Ask the maker to revise, with a mandatory comment (config-approver). */
export async function requestConfigChangesAction(
  tenantId: string,
  id: string,
  comment: string,
): Promise<ConfigRequestActionResult> {
  try {
    const request = await requestConfigChanges(tenantId, id, comment);
    revalidateAll();
    return { ok: true, request };
  } catch (err) {
    return toResult(err);
  }
}

/** Edit the proposed payload (maker; only while CHANGES_REQUESTED). */
export async function reviseConfigRequestAction(
  tenantId: string,
  id: string,
  payload: Record<string, unknown>,
): Promise<ConfigRequestActionResult> {
  try {
    const request = await reviseConfigRequest(tenantId, id, payload);
    revalidateAll();
    return { ok: true, request };
  } catch (err) {
    return toResult(err);
  }
}

/** Re-submit a revised request for approval (maker). */
export async function resubmitConfigRequestAction(
  tenantId: string,
  id: string,
): Promise<ConfigRequestActionResult> {
  try {
    const request = await resubmitConfigRequest(tenantId, id);
    revalidateAll();
    return { ok: true, request };
  } catch (err) {
    return toResult(err);
  }
}

/** Withdraw a non-terminal request (maker). */
export async function withdrawConfigRequestAction(
  tenantId: string,
  id: string,
): Promise<ConfigRequestActionResult> {
  try {
    const request = await withdrawConfigRequest(tenantId, id);
    revalidateAll();
    return { ok: true, request };
  } catch (err) {
    return toResult(err);
  }
}

/** Normalise a thrown error into the {ok:false} result shape. */
function toResult(err: unknown): ConfigRequestActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}
