/**
 * Friendly display names for config-type codes (Epic 25). Shared by every
 * surface that renders a `config_type` (open-request card, request-detail
 * drawer, config-approvals table) so a raw code like `wallet_limit` always
 * reads as "Wallet limit" and the raw value never leaks into the UI.
 */
import type { ConfigType } from "@/lib/api-types";

/** Human label for each config domain that flows through maker-checker. */
const CONFIG_TYPE_LABEL: Record<ConfigType, string> = {
  pricing: "Service charge",
  commission: "Commission",
  tax: "Tax",
  limit: "Transaction limit",
  wallet_limit: "Wallet limit",
  step_up: "Step-up PIN policy",
  conversion_rate: "Points conversion rate",
};

/**
 * Friendly display name for a config-type code.
 *
 * @param configType Raw config-type code (e.g. `wallet_limit`).
 * @returns Friendly label (e.g. `Wallet limit`).
 */
export function configTypeLabel(configType: ConfigType): string {
  return CONFIG_TYPE_LABEL[configType];
}
