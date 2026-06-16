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

import { apiDelete, apiGet, apiPost } from "@/lib/api";

import type {
  AuditEntry,
  BudgetConsumption,
  ExternalEventSource,
  LimitConfig,
  ManualReviewItem,
  PendingItem,
  PricingConfig,
  RedemptionProvider,
  RewardBudget,
  Rule,
  RulePerformance,
  SweepOutcome,
  Tenant,
  User,
  UserDetail,
} from "@/lib/api-types";

// ---- Tenants -------------------------------------------------------------

export const listTenants = () => apiGet<Tenant[]>("/api/v1/tenants");

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
  reward_type: Rule["reward_type"];
  reward_value: string;
  stop_after_n_triggers?: number;
  resets_after_trigger?: boolean;
}

export const createRule = (payload: CreateRulePayload) =>
  apiPost<Rule>("/api/v1/rules", payload);

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
