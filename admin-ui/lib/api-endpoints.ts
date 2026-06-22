/**
 * Typed wrappers around the FastAPI endpoints.
 *
 * Each function below maps 1:1 to a backend route. The UI imports from
 * here rather than calling `apiGet`/`apiPost` directly, so adding /
 * renaming an endpoint only touches one place.
 *
 * Convention: list endpoints return arrays; single-resource endpoints
 * return the resource directly; mutations return the created/updated
 * resource. Errors surface as thrown `ApiError`.
 */
import "server-only";

import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";

import type {
  AdjustSystemWalletResponse,
  AdminPinResetResponse,
  AuditEntry,
  BonusMultiplier,
  BudgetConsumption,
  ExternalEventSource,
  FundUserResponse,
  LimitConfig,
  ManualReviewItem,
  PendingItem,
  PricingConfig,
  RedemptionProvider,
  RewardBudget,
  Rule,
  RulePerformance,
  Segment,
  Service,
  StepUpPolicy,
  SweepOutcome,
  SystemWallet,
  SystemWalletTransaction,
  Tenant,
  User,
  UserDetail,
} from "@/lib/api-types";

// ---- Tenants -------------------------------------------------------------

export const listTenants = () => apiGet<Tenant[]>("/api/v1/tenants");

export const getTenant = (tenant_id: string) =>
  apiGet<Tenant>(`/api/v1/tenants/${tenant_id}`);

export interface UpdateTenantPayload {
  name?: string;
  business_type?: "wallet" | "rewards" | "both";
}

export const updateTenant = (tenant_id: string, payload: UpdateTenantPayload) =>
  apiPatch<Tenant>(`/api/v1/tenants/${tenant_id}`, payload);

// ---- Services catalog (Phase 2) -----------------------------------------

export const listServices = (
  tenant_id: string,
  status?: "active" | "disabled",
) =>
  apiGet<Service[]>("/api/v1/services", {
    query: status ? { tenant_id, status } : { tenant_id },
  });

export interface CreateServicePayload {
  tenant_id: string;
  code: string;
  display_name: string;
  description?: string;
}

export const createService = (payload: CreateServicePayload) =>
  apiPost<Service>("/api/v1/services", payload);

export interface UpdateServicePayload {
  display_name?: string;
  description?: string;
  status?: "active" | "disabled";
}

export const updateService = (
  service_id: string,
  tenant_id: string,
  payload: UpdateServicePayload,
) =>
  apiPatch<Service>(`/api/v1/services/${service_id}`, payload, {
    query: { tenant_id },
  });

export const deleteService = (service_id: string, tenant_id: string) =>
  apiDelete<Service>(`/api/v1/services/${service_id}`, { query: { tenant_id } });

// ---- Identity ------------------------------------------------------------

export interface CreateUserPayload {
  tenant_id: string;
  identifiers: {
    identifier_type: "phone" | "email" | "account_number" | "card_number";
    identifier_value: string;
    verified?: boolean;
  }[];
  profile?: {
    first_name?: string;
    last_name?: string;
    date_of_birth?: string;
  };
}

export const createUser = (payload: CreateUserPayload) =>
  apiPost<User>("/api/v1/identity/users", payload);

/**
 * Resolve any registered identifier to a user. Used by the Users page
 * search box (admin-only endpoint).
 */
export const resolveIdentifier = (
  tenant_id: string,
  identifier_type: string,
  identifier_value: string,
) =>
  apiGet<{ user_id: string; tenant_id: string; identifier_type: string }>(
    `/api/v1/identity/resolve/${identifier_type}/${encodeURIComponent(identifier_value)}`,
    { query: { tenant_id } },
  );

/**
 * Full user-detail payload — identifiers, profile, accounts with derived
 * balances. Admin-only on the backend.
 */
export const getUserDetail = (tenant_id: string, user_id: string) =>
  apiGet<UserDetail>(`/api/v1/identity/users/${user_id}`, {
    query: { tenant_id },
  });

// ---- Rules ---------------------------------------------------------------

export const listRules = (tenant_id: string) =>
  apiGet<Rule[]>("/api/v1/rules", { query: { tenant_id } });

export interface CreateRulePayload {
  tenant_id: string;
  name: string;
  description?: string;
  rule_type: Rule["rule_type"];
  transaction_type: string;
  count_threshold?: number;
  min_amount?: string;
  time_window?: string;
  // Epic 10 — rule-type-specific fields
  streak_units?: number;
  streak_unit_window?: "day" | "week";
  campaign_start_date?: string; // YYYY-MM-DD
  campaign_end_date?: string;
  reward_type: Rule["reward_type"];
  reward_value: string;
  stop_after_n_triggers?: number;
  resets_after_trigger?: boolean;
}

export const createRule = (payload: CreateRulePayload) =>
  apiPost<Rule>("/api/v1/rules", payload);

/** Fetch one rule (admin only, tenant-scoped). */
export const getRule = (rule_id: string, tenant_id: string) =>
  apiGet<Rule>(`/api/v1/rules/${rule_id}`, { query: { tenant_id } });

export interface UpdateRulePayload {
  name?: string;
  description?: string;
  reward_value?: string;
  stop_after_n_triggers?: number;
  status?: "active" | "inactive";
}

/** Patch a rule's editable fields. Trigger conditions are immutable. */
export const updateRule = (
  rule_id: string,
  tenant_id: string,
  payload: UpdateRulePayload,
) =>
  apiPatch<Rule>(`/api/v1/rules/${rule_id}`, payload, {
    query: { tenant_id },
  });

/** Soft-delete (status='inactive'). Idempotent. */
export const deleteRule = (rule_id: string, tenant_id: string) =>
  apiDelete<void>(`/api/v1/rules/${rule_id}`, { query: { tenant_id } });

/**
 * Campaign performance metrics — total fires, unique users rewarded,
 * total reward value, and first/last fire timestamps. Backend computes
 * these live from `reward_events`.
 */
export const getRulePerformance = (rule_id: string, tenant_id: string) =>
  apiGet<RulePerformance>(`/api/v1/rules/${rule_id}/performance`, {
    query: { tenant_id },
  });

// ---- Redemption ----------------------------------------------------------

export interface RegisterProviderPayload {
  tenant_id: string;
  name: string;
  status_check_url?: string;
  max_retries?: number;
  retry_interval_secs?: number;
  escalate_after_mins?: number;
  shared_secret?: string;
}

export const registerProvider = (payload: RegisterProviderPayload) =>
  apiPost<RedemptionProvider>("/api/v1/redemption/providers", payload);

// ---- Events --------------------------------------------------------------

export interface RegisterEventSourcePayload {
  tenant_id: string;
  name: string;
  source_key: string;
  field_mapping?: Record<string, unknown>;
  shared_secret?: string;
}

export const registerEventSource = (payload: RegisterEventSourcePayload) =>
  apiPost<ExternalEventSource>("/api/v1/events/sources", payload);

// ---- Reconciliation -----------------------------------------------------

export const listPendingRedemptions = (
  tenant_id: string,
  threshold_minutes = 5,
) =>
  apiGet<PendingItem[]>("/api/v1/reconciliation/pending", {
    query: { tenant_id, threshold_minutes },
  });

export const listManualReview = (tenant_id: string) =>
  apiGet<ManualReviewItem[]>("/api/v1/reconciliation/manual-review", {
    query: { tenant_id },
  });

export interface SweepRequest {
  tenant_id: string;
  threshold_minutes?: number;
}

export const triggerSweep = (payload: SweepRequest) =>
  apiPost<SweepOutcome>("/api/v1/reconciliation/sweep", payload);

// ---- Audit log -----------------------------------------------------------

export interface AuditQuery {
  tenant_id: string;
  entity_type?: string;
  entity_id?: string;
  limit?: number;
}

export const queryAuditLog = (q: AuditQuery) =>
  apiGet<AuditEntry[]>("/api/v1/reconciliation/audit", {
    query: {
      tenant_id: q.tenant_id,
      entity_type: q.entity_type,
      entity_id: q.entity_id,
      limit: q.limit,
    },
  });

// ---- Phase G — Limits, Pricing, Budgets ---------------------------------

export interface CreateLimitConfigPayload {
  tenant_id: string;
  transaction_type: string;
  account_type: string;
  currency: string;
  min_amount?: string;
  max_amount?: string;
  daily_count_cap?: number;
  daily_value_cap?: string;
}

export const listLimitConfigs = (tenant_id: string) =>
  apiGet<LimitConfig[]>("/api/v1/limits/configs", { query: { tenant_id } });

export const createLimitConfig = (payload: CreateLimitConfigPayload) =>
  apiPost<LimitConfig>("/api/v1/limits/configs", payload);

export const deleteLimitConfig = (config_id: string, tenant_id: string) =>
  apiDelete<void>(`/api/v1/limits/configs/${config_id}`, {
    query: { tenant_id },
  });

export interface CreatePricingConfigPayload {
  tenant_id: string;
  transaction_type: string;
  account_type: string;
  currency: string;
  fixed_fee?: string;
  variable_fee_pct?: string;
  fee_cap?: string;
}

export const listPricingConfigs = (tenant_id: string) =>
  apiGet<PricingConfig[]>("/api/v1/pricing/configs", { query: { tenant_id } });

export const createPricingConfig = (payload: CreatePricingConfigPayload) =>
  apiPost<PricingConfig>("/api/v1/pricing/configs", payload);

export const deletePricingConfig = (config_id: string, tenant_id: string) =>
  apiDelete<void>(`/api/v1/pricing/configs/${config_id}`, {
    query: { tenant_id },
  });

export interface CreateBudgetPayload {
  tenant_id: string;
  scope_type: "tenant" | "rule";
  scope_id?: string;
  currency: string;
  window_type: "rolling_24h" | "rolling_7d" | "calendar_month" | "lifetime";
  cap_amount: string;
  status?: "active" | "paused";
}

export const listBudgets = (tenant_id: string) =>
  apiGet<BudgetConsumption[]>("/api/v1/budgets", { query: { tenant_id } });

export const createBudget = (payload: CreateBudgetPayload) =>
  apiPost<RewardBudget>("/api/v1/budgets", payload);

export const deleteBudget = (budget_id: string, tenant_id: string) =>
  apiDelete<void>(`/api/v1/budgets/${budget_id}`, { query: { tenant_id } });

// ---- Phase H — Step-up PIN policies + admin PIN reset --------------------

export interface CreateStepUpPolicyPayload {
  tenant_id: string;
  transaction_type: "p2p" | "redemption";
  currency: string;
  threshold_amount: string;
}

export const listStepUpPolicies = (tenant_id: string) =>
  apiGet<StepUpPolicy[]>("/api/v1/step-up/policies", { query: { tenant_id } });

export const createStepUpPolicy = (payload: CreateStepUpPolicyPayload) =>
  apiPost<StepUpPolicy>("/api/v1/step-up/policies", payload);

export const deleteStepUpPolicy = (policy_id: string, tenant_id: string) =>
  apiDelete<void>(`/api/v1/step-up/policies/${policy_id}`, {
    query: { tenant_id },
  });

/**
 * Admin-triggered PIN reset — generates a new random 4-digit PIN,
 * bcrypt-stores it, returns the plaintext (Phase 2 swaps this for
 * SMS delivery via the notifications module).
 */
export const adminResetPin = (user_id: string, tenant_id: string) =>
  apiPost<AdminPinResetResponse>(
    `/api/v1/identity/users/${user_id}/pin/reset`,
    undefined,
    { query: { tenant_id } },
  );

// ---- Phase H — Treasury / System Wallets --------------------------------

export const listSystemWallets = (tenant_id: string) =>
  apiGet<SystemWallet[]>("/api/v1/treasury/system-wallets", {
    query: { tenant_id },
  });

export const listSystemWalletTransactions = (
  account_id: string,
  tenant_id: string,
  limit = 50,
) =>
  apiGet<SystemWalletTransaction[]>(
    `/api/v1/treasury/system-wallets/${account_id}/transactions`,
    { query: { tenant_id, limit } },
  );

export interface FundUserPayload {
  tenant_id: string;
  user_id: string;
  amount: string;
  currency: string;
  reason: string;
}

export const fundUser = (payload: FundUserPayload) =>
  apiPost<FundUserResponse>("/api/v1/treasury/fund-user", payload);

export interface AdjustSystemWalletPayload {
  tenant_id: string;
  account_id: string;
  amount: string; // signed
  reason: string;
}

export const adjustSystemWallet = (payload: AdjustSystemWalletPayload) =>
  apiPost<AdjustSystemWalletResponse>(
    "/api/v1/treasury/adjust-system-wallet",
    payload,
  );

// ---- Phase H — Segments + Bonus Multipliers ------------------------------

export interface CreateSegmentPayload {
  tenant_id: string;
  name: string;
  description?: string;
}

export const listSegments = (tenant_id: string) =>
  apiGet<Segment[]>("/api/v1/segments", { query: { tenant_id } });

export const createSegment = (payload: CreateSegmentPayload) =>
  apiPost<Segment>("/api/v1/segments", payload);

export const addUserToSegment = (
  segment_id: string,
  tenant_id: string,
  user_id: string,
) =>
  apiPost<{ segment_id: string; user_id: string }>(
    `/api/v1/segments/${segment_id}/users`,
    { user_id },
    { query: { tenant_id } },
  );

export interface CreateMultiplierPayload {
  tenant_id: string;
  rule_id?: string;
  segment_id?: string;
  multiplier: string;
  valid_from?: string;
  valid_until?: string;
}

export const listMultipliers = (tenant_id: string) =>
  apiGet<BonusMultiplier[]>("/api/v1/multipliers", { query: { tenant_id } });

export const createMultiplier = (payload: CreateMultiplierPayload) =>
  apiPost<BonusMultiplier>("/api/v1/multipliers", payload);

export const deleteMultiplier = (multiplier_id: string, tenant_id: string) =>
  apiDelete<void>(`/api/v1/multipliers/${multiplier_id}`, {
    query: { tenant_id },
  });
