/**
 * Server actions for the Taxes screen (Epic 24 / Story 24.2).
 *
 * Tax writes go through the maker-checker pipeline: these actions PROPOSE a
 * create/delete via `POST /config-requests` (status PENDING). Approval by a
 * second admin (Story 24.3) applies the change.
 */
"use server";

import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { proposeConfigChange } from "@/lib/api-endpoints";

export type TaxActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/** Fields the tax create dialog collects (percentages are strings). */
export interface ProposeTaxInput {
  tenant_id: string;
  currency: string;
  fee_tax_pct: string;
  commission_tax_pct: string;
  fee_tax_inclusive: boolean;
  commission_tax_inclusive: boolean;
}

/** Propose creating a tax config. */
export async function proposeTaxChangeAction(
  input: ProposeTaxInput,
): Promise<TaxActionResult> {
  try {
    await proposeConfigChange(input.tenant_id, {
      config_type: "tax",
      operation: "create",
      payload: { ...input },
    });
    revalidatePath("/taxes");
    revalidatePath("/config-requests");
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Propose deleting a tax config by id. */
export async function proposeTaxDeleteAction(
  configId: string,
  tenantId: string,
): Promise<TaxActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "tax",
      operation: "delete",
      target_config_id: configId,
    });
    revalidatePath("/taxes");
    revalidatePath("/config-requests");
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Normalise a thrown error into the {ok:false} result shape. */
function toResult(err: unknown): TaxActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}
