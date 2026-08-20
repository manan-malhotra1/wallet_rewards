/**
 * Friendly display labels for ledger account types. Single source of truth —
 * shared by the system-wallets table, user detail, and the money-approvals
 * summaries/drawer so a raw type key like `system_cash_inflow` never reaches
 * an operator's screen.
 */

/** account_type → operator-facing label. Keep in sync with new account types. */
export const ACCOUNT_TYPE_LABEL: Record<string, string> = {
  financial_wallet: "Financial wallet",
  points_account: "Points",
  system_cash_inflow: "Cash float",
  system_points_issuance: "Points issuance pool",
  system_fee_collected: "Fees collected",
  provider_redemption_wallet: "Provider redemption wallet",
  operator_adjustment: "Bank Mirror Account",
  commission: "Commission Funded Wallet",
  tax_service_collected: "Tax Collected on Service Charges",
  tax_commission_collected: "Tax Collected on Commissions",
  airtime_merchant_holding: "Airtime merchant holding",
  cashback_provider_wallet: "Cashback & Redemption Wallet",
  points_redemption_wallet: "Points Redemption Wallet",
};

/**
 * Friendly label for an account type key. Values that aren't a known type key
 * (custom wallet names like "Steward Bank", or a future type) pass through
 * unchanged, so this is safe to apply to any account display name.
 */
export function accountTypeLabel(value: string): string {
  return ACCOUNT_TYPE_LABEL[value] ?? value;
}
