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
  getConfigHistory,
  getConfigRequest,
  proposeConfigChange,
  requestConfigChanges,
  resubmitConfigRequest,
  reviseConfigRequest,
  withdrawConfigRequest,
} from "@/lib/api-endpoints";
import type { ConfigChangeRequest, ConfigType } from "@/lib/api-types";

export type ConfigRequestActionResult =
  | { ok: true; request: ConfigChangeRequest }
  | { ok: false; errorCode: string; message: string };

/** Result of loading a live config's applied-version history. */
export type ConfigHistoryActionResult =
  | { ok: true; versions: ConfigChangeRequest[] }
  | { ok: false; errorCode: string; message: string };

/** Result of proposing a generic config update (no request echoed back). */
export type ConfigUpdateActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/** Config pages whose data may change once a request is applied. */
const CONFIG_PATHS = ["/pricing", "/commissions", "/taxes", "/limits", "/step-up"];

function revalidateAll() {
  // The config queue now lives under the unified /approvals page.
  revalidatePath("/approvals");
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

/**
 * Load the applied-version history for one live config row (Epic 25). Client
 * components can't call the API endpoint directly, so the View drawer routes
 * through this action. Versions are oldest-first; the last is the live config.
 */
export async function loadConfigHistoryAction(
  tenantId: string,
  configType: ConfigType,
  targetConfigId: string,
): Promise<ConfigHistoryActionResult> {
  try {
    const versions = await getConfigHistory(tenantId, configType, targetConfigId);
    return { ok: true, versions };
  } catch (err) {
    return { ok: false, ...toError(err) };
  }
}

/**
 * Propose restoring a prior version of any config type (Epic 25). Re-proposes
 * that version's `payload` as an `update` against the live row — it routes to
 * the checker (status PENDING) and does NOT apply immediately. Generic across
 * all five config types since it's driven by the shared View drawer.
 */
export async function proposeConfigUpdateAction(
  tenantId: string,
  configType: ConfigType,
  targetConfigId: string,
  payload: Record<string, unknown>,
): Promise<ConfigUpdateActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: configType,
      operation: "update",
      payload,
      target_config_id: targetConfigId,
    });
    revalidateAll();
    return { ok: true };
  } catch (err) {
    return { ok: false, ...toError(err) };
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

/**
 * Revise the payload and re-submit for approval in one maker action (Epic 25).
 * Powers the form-based "Edit & resubmit" flow on the native config pages: it
 * PATCHes the revised payload, then flips the request back to PENDING.
 */
export async function reviseAndResubmitConfigRequestAction(
  tenantId: string,
  id: string,
  payload: Record<string, unknown>,
): Promise<ConfigRequestActionResult> {
  try {
    await reviseConfigRequest(tenantId, id, payload);
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

/** Extract the {errorCode, message} pair from any thrown error. */
function toError(err: unknown): { errorCode: string; message: string } {
  if (err instanceof ApiError) {
    return { errorCode: err.errorCode, message: err.message };
  }
  return {
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}

/** Normalise a thrown error into the {ok:false} result shape. */
function toResult(err: unknown): ConfigRequestActionResult {
  return { ok: false, ...toError(err) };
}
