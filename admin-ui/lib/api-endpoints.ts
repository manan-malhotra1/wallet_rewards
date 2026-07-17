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
  AdminPinResetResponse,
  ApiKey,
  ApiKeyCreated,
  AuditEntry,
  BonusMultiplier,
  BudgetConsumption,
  CommissionConfig,
  CompositeOperator,
  ConfigChangeRequest,
  ConfigOperation,
  ConfigRequestStatus,
  ConfigType,
  ExternalEventSource,
  Instrument,
  LimitConfig,
  ManualReviewItem,
  MoneyOperation,
  MoneyOperationStatus,
  PendingItem,
  PricingConfig,
  RedemptionProvider,
  ReferralTrigger,
  RewardBudget,
  Rule,
  RuleCondition,
  RulePerformance,
  Segment,
  Service,
  StepUpPolicy,
  SweepOutcome,
  SystemWallet,
  SystemWalletTransaction,
  TaxConfig,
  Tenant,
  User,
  UserDetail,
  UserOperation,
  UserOperationStatus,
  UserType,
  WalletLimitConfig,
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

// ---- Instruments catalog (Phase 3) --------------------------------------

export const listInstruments = (
  tenant_id: string,
  status?: "active" | "disabled",
) =>
  apiGet<Instrument[]>("/api/v1/instruments", {
    query: status ? { tenant_id, status } : { tenant_id },
  });

export interface CreateInstrumentPayload {
  tenant_id: string;
  code: string;
  symbol: string;
  display_name: string;
  description?: string;
  account_type: "financial_wallet" | "points_account";
  assign_to_existing_users?: boolean;
}

export const createInstrument = (payload: CreateInstrumentPayload) =>
  apiPost<Instrument>("/api/v1/instruments", payload);

export interface UpdateInstrumentPayload {
  symbol?: string;
  display_name?: string;
  description?: string;
  status?: "active" | "disabled";
}

export const updateInstrument = (
  instrument_id: string,
  tenant_id: string,
  payload: UpdateInstrumentPayload,
) =>
  apiPatch<Instrument>(`/api/v1/instruments/${instrument_id}`, payload, {
    query: { tenant_id },
  });

export const deleteInstrument = (instrument_id: string, tenant_id: string) =>
  apiDelete<Instrument>(`/api/v1/instruments/${instrument_id}`, {
    query: { tenant_id },
  });

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
  // Epic 12/13 — user type + optional hierarchy parent. Default consumer.
  user_type?: UserType;
  parent_user_id?: string;
}

export const createUser = (payload: CreateUserPayload) =>
  apiPost<User>("/api/v1/identity/users", payload);

export interface ChangeUserTypePayload {
  new_type: UserType;
  /** Only valid for agent/merchant types; null clears the parent. */
  parent_user_id?: string | null;
  /** Mandatory — recorded on the audit log entry. */
  reason: string;
}

/**
 * Change a user's type (+ optional parent). Admin-only, tenant-scoped,
 * audit-logged. Idempotent by state on the backend.
 */
export const changeUserType = (
  user_id: string,
  tenant_id: string,
  payload: ChangeUserTypePayload,
) =>
  apiPatch<User>(`/api/v1/identity/users/${user_id}/type`, payload, {
    query: { tenant_id },
  });

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

/** One row in the admin user-detail Transactions table. */
export interface UserTransaction {
  id: string;
  /** Customer-facing reference S_<datetime><seq>; null for un-backfilled legacy rows. */
  reference: string | null;
  transaction_type: string;
  status: string;
  amount: string;
  /** Service charge debited with this transaction. "0" when none applied. */
  fee_amount: string;
  currency: string;
  created_at: string;
  direction: "in" | "out";
  counterparty_name: string | null;
}

export const listUserTransactions = (
  tenant_id: string,
  user_id: string,
  limit: number = 50,
) =>
  apiGet<UserTransaction[]>(
    `/api/v1/identity/users/${user_id}/transactions`,
    { query: { tenant_id, limit } },
  );

// ---- Rules ---------------------------------------------------------------

export const listRules = (tenant_id: string) =>
  apiGet<Rule[]>("/api/v1/rules", { query: { tenant_id } });

export interface CreateRulePayload {
  tenant_id: string;
  name: string;
  description?: string;
  rule_type: Rule["rule_type"];
  // Optional: composite rules carry no top-level transaction_type (it
  // lives on each sub-condition); referral rules don't use it either.
  transaction_type?: string;
  count_threshold?: number;
  min_amount?: string;
  time_window?: string;
  // Epic 10 — rule-type-specific fields
  streak_units?: number;
  streak_unit_window?: "day" | "week";
  campaign_start_date?: string; // YYYY-MM-DD
  campaign_end_date?: string;
  // Epic 10 / WAL-75 — composite operator + >=2 sub-conditions.
  composite_operator?: CompositeOperator;
  conditions?: RuleCondition[];
  // Epic 10 / WAL-77 — referral trigger + optional referee reward.
  referral_trigger?: ReferralTrigger;
  referral_trigger_n?: number;
  referee_reward_value?: string;
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
  user_type?: UserType | null;
  min_amount?: string;
  max_amount?: string;
  daily_count_cap?: number;
  daily_value_cap?: string;
  weekly_count_cap?: number;
  weekly_value_cap?: string;
  monthly_count_cap?: number;
  monthly_value_cap?: string;
}

// Since maker-checker, limit + wallet-limit writes flow through
// `proposeConfigChange`; the direct create/delete endpoints were removed on the
// backend. Reads stay direct. The Create*Payload types double as propose payloads.
export const listLimitConfigs = (tenant_id: string) =>
  apiGet<LimitConfig[]>("/api/v1/limits/configs", { query: { tenant_id } });

export interface CreateWalletLimitConfigPayload {
  tenant_id: string;
  currency: string;
  user_type?: UserType | null;
  max_balance?: string;
  send_daily_count_cap?: number;
  send_daily_value_cap?: string;
  send_weekly_count_cap?: number;
  send_weekly_value_cap?: string;
  send_monthly_count_cap?: number;
  send_monthly_value_cap?: string;
  receive_daily_count_cap?: number;
  receive_daily_value_cap?: string;
  receive_weekly_count_cap?: number;
  receive_weekly_value_cap?: string;
  receive_monthly_count_cap?: number;
  receive_monthly_value_cap?: string;
}

export const listWalletLimitConfigs = (tenant_id: string) =>
  apiGet<WalletLimitConfig[]>("/api/v1/limits/wallet-configs", {
    query: { tenant_id },
  });

// Since Epic 22 all pricing writes flow through the maker-checker pipeline
// (see `proposeConfigChange` below). The old direct create/delete pricing
// endpoints were removed on the backend — reads stay direct.
export const listPricingConfigs = (tenant_id: string) =>
  apiGet<PricingConfig[]>("/api/v1/pricing/configs", { query: { tenant_id } });

// ---- Epic 24 — Commission + Tax configs (read-only; writes via propose) --

export const listCommissionConfigs = (tenant_id: string) =>
  apiGet<CommissionConfig[]>("/api/v1/commissions/configs", {
    query: { tenant_id },
  });

export const listTaxConfigs = (tenant_id: string) =>
  apiGet<TaxConfig[]>("/api/v1/taxes/configs", { query: { tenant_id } });

// ---- Epic 24 — Config change requests (maker-checker) --------------------

/**
 * Body for proposing a config change. `payload` carries the matching create
 * schema (including tenant_id) for create ops; `target_config_id` names the
 * row to remove for delete ops.
 */
export interface ProposeConfigChangePayload {
  config_type: ConfigType;
  operation: ConfigOperation;
  payload?: Record<string, unknown>;
  target_config_id?: string;
}

/** Propose a create/delete against a config domain. Returns the PENDING request. */
export const proposeConfigChange = (
  tenant_id: string,
  payload: ProposeConfigChangePayload,
) =>
  apiPost<ConfigChangeRequest>("/api/v1/config-requests", payload, {
    query: { tenant_id },
  });

/**
 * List change requests, optionally filtered by lifecycle status and/or the
 * config domain (`config_type`). Native config pages pass `config_type` to
 * fetch only their own CHANGES_REQUESTED items.
 */
export const listConfigRequests = (
  tenant_id: string,
  status_filter?: ConfigRequestStatus,
  config_type?: ConfigType,
) =>
  apiGet<ConfigChangeRequest[]>("/api/v1/config-requests", {
    query: { tenant_id, status_filter, config_type },
  });

/**
 * Full applied-version history for one live config row (Epic 25 — version
 * history + restore). Returns every APPLIED change request that targeted this
 * config, ordered oldest-first; the LAST element is the current live config,
 * earlier ones are prior versions. 404 if the target no longer exists.
 */
export const getConfigHistory = (
  tenant_id: string,
  config_type: ConfigType,
  target_config_id: string,
) =>
  apiGet<ConfigChangeRequest[]>("/api/v1/config-requests/history", {
    query: { tenant_id, config_type, target_config_id },
  });

/** Fetch a single change request with its review thread. */
export const getConfigRequest = (tenant_id: string, id: string) =>
  apiGet<ConfigChangeRequest>(`/api/v1/config-requests/${id}`, {
    query: { tenant_id },
  });

/** Approve a request (config-approver; must differ from the maker). */
export const approveConfigRequest = (tenant_id: string, id: string) =>
  apiPost<ConfigChangeRequest>(
    `/api/v1/config-requests/${id}/approve`,
    undefined,
    { query: { tenant_id } },
  );

/** Ask the maker to revise (config-approver). Comment is mandatory. */
export const requestConfigChanges = (
  tenant_id: string,
  id: string,
  comment: string,
) =>
  apiPost<ConfigChangeRequest>(
    `/api/v1/config-requests/${id}/request-changes`,
    { comment },
    { query: { tenant_id } },
  );

/** Edit the proposed payload (maker; only while CHANGES_REQUESTED). */
export const reviseConfigRequest = (
  tenant_id: string,
  id: string,
  payload: Record<string, unknown>,
) =>
  apiPatch<ConfigChangeRequest>(
    `/api/v1/config-requests/${id}`,
    { payload },
    { query: { tenant_id } },
  );

/** Re-submit a revised request for approval (maker). */
export const resubmitConfigRequest = (tenant_id: string, id: string) =>
  apiPost<ConfigChangeRequest>(
    `/api/v1/config-requests/${id}/resubmit`,
    undefined,
    { query: { tenant_id } },
  );

/** Withdraw a non-terminal request (maker). */
export const withdrawConfigRequest = (tenant_id: string, id: string) =>
  apiPost<ConfigChangeRequest>(
    `/api/v1/config-requests/${id}/withdraw`,
    undefined,
    { query: { tenant_id } },
  );

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

export type TreasuryIdentifierType =
  | "phone"
  | "email"
  | "account_number"
  | "card_number";

export interface FundUserPayload {
  tenant_id: string;
  identifier_type: TreasuryIdentifierType;
  identifier_value: string;
  amount: string;
  currency: string;
  reason: string;
}

/**
 * PROPOSE a fund (Epic 18 maker-checker). No longer executes directly —
 * returns a PENDING `MoneyOperation` that posts only after N-eyes approval.
 */
export const fundUser = (payload: FundUserPayload) =>
  apiPost<MoneyOperation>("/api/v1/treasury/fund-user", payload);

export interface WithdrawFromUserPayload {
  tenant_id: string;
  identifier_type: TreasuryIdentifierType;
  identifier_value: string;
  amount: string;
  currency: string;
  reason: string;
  /** The chosen bank-mirror (operator_adjustment) account to use as the counter-leg. */
  bank_mirror_account_id: string;
}

/** PROPOSE a pull-back (Epic 18). Returns a PENDING `MoneyOperation`. */
export const withdrawFromUser = (payload: WithdrawFromUserPayload) =>
  apiPost<MoneyOperation>("/api/v1/treasury/withdraw", payload);

export interface AdjustSystemWalletPayload {
  tenant_id: string;
  account_id: string;
  amount: string; // signed
  reason: string;
  /** The chosen bank-mirror (operator_adjustment) account to use as the counter-leg. */
  bank_mirror_account_id: string;
}

// ---- Bank mirrors (named operator_adjustment accounts) -------------------

export interface CreateBankMirrorPayload {
  currency: string;
  name: string;
}

/**
 * PROPOSE a named bank-mirror account (Epic 18). Returns a PENDING
 * `MoneyOperation`; the account is created only after N-eyes approval.
 * Duplicate-name collision surfaces at approval/apply time.
 */
export const createBankMirror = (
  tenant_id: string,
  payload: CreateBankMirrorPayload,
) =>
  apiPost<MoneyOperation>("/api/v1/treasury/bank-mirrors", payload, {
    query: { tenant_id },
  });

/** Rename an existing bank-mirror account. Collision → 409; unknown → 404. */
export const renameBankMirror = (
  tenant_id: string,
  account_id: string,
  payload: { name: string },
) =>
  apiPatch<SystemWallet>(
    `/api/v1/treasury/bank-mirrors/${account_id}`,
    payload,
    { query: { tenant_id } },
  );

/** PROPOSE a signed system-wallet adjust (Epic 18). Returns a PENDING `MoneyOperation`. */
export const adjustSystemWallet = (payload: AdjustSystemWalletPayload) =>
  apiPost<MoneyOperation>(
    "/api/v1/treasury/adjust-system-wallet",
    payload,
  );

// ---- Epic 18 — Money operations (maker-checker review verbs) -------------

/** List a tenant's money operations, optionally filtered by lifecycle status. */
export const listMoneyOperations = (
  tenant_id: string,
  status_filter?: MoneyOperationStatus,
) =>
  apiGet<MoneyOperation[]>("/api/v1/money-operations", {
    query: { tenant_id, status_filter },
  });

/** Fetch a single money operation with its full review thread + progress. */
export const getMoneyOperation = (id: string, tenant_id: string) =>
  apiGet<MoneyOperation>(`/api/v1/money-operations/${id}`, {
    query: { tenant_id },
  });

/** Approve a money operation (treasury-approver; must differ from the maker). */
export const approveMoneyOperation = (tenant_id: string, id: string) =>
  apiPost<MoneyOperation>(
    `/api/v1/money-operations/${id}/approve`,
    undefined,
    { query: { tenant_id } },
  );

/** Ask the maker to revise (treasury-approver). Comment is mandatory. */
export const requestMoneyOpChanges = (
  tenant_id: string,
  id: string,
  comment: string,
) =>
  apiPost<MoneyOperation>(
    `/api/v1/money-operations/${id}/request-changes`,
    { comment },
    { query: { tenant_id } },
  );

/** Edit the proposed payload (maker; only while CHANGES_REQUESTED). */
export const reviseMoneyOperation = (
  tenant_id: string,
  id: string,
  payload: Record<string, unknown>,
) =>
  apiPatch<MoneyOperation>(
    `/api/v1/money-operations/${id}`,
    { payload },
    { query: { tenant_id } },
  );

/** Re-submit a revised operation for approval → fresh round (maker). */
export const resubmitMoneyOperation = (tenant_id: string, id: string) =>
  apiPost<MoneyOperation>(
    `/api/v1/money-operations/${id}/resubmit`,
    undefined,
    { query: { tenant_id } },
  );

/** Withdraw a non-terminal money operation (maker). */
export const withdrawMoneyOperation = (tenant_id: string, id: string) =>
  apiPost<MoneyOperation>(
    `/api/v1/money-operations/${id}/withdraw`,
    undefined,
    { query: { tenant_id } },
  );

// ---- Epic 3 — User operations (create/edit user maker-checker) -----------

/**
 * PROPOSE a user operation (create_user / update_user). Returns a PENDING
 * `UserOperation`; the user is created/edited only after N-eyes approval.
 * `tenant_id` is a query param (admins are cross-tenant), matching money ops.
 */
export const proposeUserOperation = (
  tenant_id: string,
  operation: "create_user" | "update_user",
  payload: Record<string, unknown>,
) =>
  apiPost<UserOperation>(
    "/api/v1/user-operations",
    { operation, payload },
    { query: { tenant_id } },
  );

/** List a tenant's user operations, optionally filtered by lifecycle status. */
export const listUserOperations = (
  tenant_id: string,
  status_filter?: UserOperationStatus,
) =>
  apiGet<UserOperation[]>("/api/v1/user-operations", {
    query: { tenant_id, status_filter },
  });

/** Fetch a single user operation with its full review thread + progress. */
export const getUserOperation = (id: string, tenant_id: string) =>
  apiGet<UserOperation>(`/api/v1/user-operations/${id}`, {
    query: { tenant_id },
  });

/** Approve a user operation (user-approver; must differ from the maker). */
export const approveUserOperation = (tenant_id: string, id: string) =>
  apiPost<UserOperation>(
    `/api/v1/user-operations/${id}/approve`,
    undefined,
    { query: { tenant_id } },
  );

/** Ask the maker to revise (user-approver). Comment is mandatory. */
export const requestUserOpChanges = (
  tenant_id: string,
  id: string,
  comment: string,
) =>
  apiPost<UserOperation>(
    `/api/v1/user-operations/${id}/request-changes`,
    { comment },
    { query: { tenant_id } },
  );

/** Edit the proposed payload (maker; only while CHANGES_REQUESTED). */
export const reviseUserOperation = (
  tenant_id: string,
  id: string,
  payload: Record<string, unknown>,
) =>
  apiPatch<UserOperation>(
    `/api/v1/user-operations/${id}`,
    { payload },
    { query: { tenant_id } },
  );

/** Re-submit a revised operation for approval → fresh round (maker). */
export const resubmitUserOperation = (tenant_id: string, id: string) =>
  apiPost<UserOperation>(
    `/api/v1/user-operations/${id}/resubmit`,
    undefined,
    { query: { tenant_id } },
  );

/** Withdraw a non-terminal user operation (maker). */
export const withdrawUserOperation = (tenant_id: string, id: string) =>
  apiPost<UserOperation>(
    `/api/v1/user-operations/${id}/withdraw`,
    undefined,
    { query: { tenant_id } },
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

export interface CreateApiKeyPayload {
  tenant_id: string;
  label?: string;
  /**
   * Optional merchant user (user_type merchant/head_merchant) to bind the key
   * to. When set, the minted key can call the external merchant cash-in API.
   * Omit/null for a standard partner key. Backend 422s `merchant_user_required`
   * if the id is not a merchant-type user in the tenant.
   */
  merchant_user_id?: string | null;
}

export const listApiKeys = (tenant_id: string) =>
  apiGet<ApiKey[]>("/api/v1/api-keys", { query: { tenant_id } });

export const createApiKey = (payload: CreateApiKeyPayload) =>
  apiPost<ApiKeyCreated>("/api/v1/api-keys", payload);

export const revokeApiKey = (key_pk: string, tenant_id: string) =>
  apiPost<ApiKey>(`/api/v1/api-keys/${key_pk}/revoke`, undefined, {
    query: { tenant_id },
  });
