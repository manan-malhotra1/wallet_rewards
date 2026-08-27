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

import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "@/lib/api";

import type {
  ActiveUsers,
  AddUserIdentifierPayload,
  AdminAccessResponse,
  AdminPinResetResponse,
  AdminUnlockResponse,
  AnalyticsGranularity,
  AnalyticsRange,
  ApiKey,
  ApiKeyCreated,
  AuditEntry,
  BonusMultiplier,
  BudgetConsumption,
  CommissionBatch,
  CommissionConfig,
  CompositeOperator,
  ConfigChangeRequest,
  ConfigOperation,
  ConfigRequestStatus,
  ConfigType,
  CurrencyInfo,
  CurrencyLiquidity,
  DashboardSummary,
  ExternalEventSource,
  Instrument,
  LimitConfig,
  ManualReviewItem,
  MemberCounts,
  MetricsTimeseries,
  MoneyOperation,
  MoneyOperationStatus,
  NetFlowPoint,
  PendingItem,
  PointsConversionRate,
  PricingConfig,
  QueueCounts,
  RedemptionProvider,
  ReferralTrigger,
  RevenueServiceSlice,
  RewardBudget,
  RewardsTimeseries,
  Rule,
  RuleCondition,
  RulePerformance,
  Segment,
  SegmentCriteriaDoc,
  SegmentGroup,
  SegmentMetricInfo,
  Service,
  ServiceSlice,
  SettableAccessLevel,
  StatusBucket,
  StepUpPolicy,
  SweepOutcome,
  SystemWallet,
  SystemWalletTransaction,
  TaxConfig,
  Tenant,
  TenantBranding,
  User,
  UserDetail,
  UserIdentifier,
  UserOperation,
  UserOperationStatus,
  UserType,
  UserTypeCatalog,
  UserTypeSlice,
  UsersTimeseries,
  WalletLimitConfig,
} from "@/lib/api-types";

// ---- Tenants -------------------------------------------------------------

export const listTenants = () => apiGet<Tenant[]>("/api/v1/tenants");

export const getTenant = (tenant_id: string) =>
  apiGet<Tenant>(`/api/v1/tenants/${tenant_id}`);

/**
 * Body for provisioning a new tenant. The backend upper-cases `base_currency`
 * and auto-provisions the tenant's baseline instruments/services. Optional
 * branding fields seed the runtime palette; omit / null to inherit defaults.
 */
export interface CreateTenantPayload {
  name: string;
  business_type: "wallet" | "rewards" | "both";
  base_currency: string;
  brand_accent_color?: string | null;
  brand_light_color?: string | null;
  brand_icon_url?: string | null;
}

/** Create a tenant (platform-admin). Returns the created Tenant (201). */
export const createTenant = (payload: CreateTenantPayload) =>
  apiPost<Tenant>("/api/v1/tenants", payload);

export interface UpdateTenantPayload {
  name?: string;
  business_type?: "wallet" | "rewards" | "both";
}

export const updateTenant = (tenant_id: string, payload: UpdateTenantPayload) =>
  apiPatch<Tenant>(`/api/v1/tenants/${tenant_id}`, payload);

/** Read a tenant's cosmetic branding (platform-admin only). */
export const getTenantBranding = (tenant_id: string) =>
  apiGet<TenantBranding>(`/api/v1/tenants/${tenant_id}/branding`);

/** Set a tenant's cosmetic branding directly (not maker-checker). */
export const updateTenantBranding = (
  tenant_id: string,
  payload: TenantBranding,
) => apiPut<TenantBranding>(`/api/v1/tenants/${tenant_id}/branding`, payload);

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
  /**
   * Required: this endpoint only creates DERIVED services. Base services ship
   * with the platform, so there is no "create a base" path to omit this for.
   */
  base_service_code: string;
  /**
   * Access policy on create. `null` (or omitted) = unrestricted; `[]` =
   * restrict to none; a list = allow-list. See the `Service` type.
   *
   * Narrowing-only: the backend rejects (422 `policy_wider_than_base`) any
   * value that permits a user_type or channel the base itself excludes.
   */
  allowed_user_types?: string[] | null;
  allowed_channels?: string[] | null;
}

export const createService = (payload: CreateServicePayload) =>
  apiPost<Service>("/api/v1/services", payload);

export interface UpdateServicePayload {
  display_name?: string;
  description?: string;
  status?: "active" | "disabled";
  /**
   * Access policy on update. Omit to leave unchanged; `null` = unrestricted;
   * `[]` = restrict to none; a list = allow-list. See the `Service` type.
   */
  allowed_user_types?: string[] | null;
  allowed_channels?: string[] | null;
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

// ---- User-type catalog ---------------------------------------------------

/**
 * Fetch the user-type catalog for a tenant (categories + visible types).
 *
 * Types come back already ordered by the category's `display_order`, then
 * label — callers render them in the order given.
 *
 * @param tenant_id - Tenant whose catalog to read.
 * @param include_retired - Include retired types (the `/user-types` admin page
 *   wants them; pickers do not).
 */
export const getUserTypeCatalog = (tenant_id: string, include_retired = false) =>
  apiGet<UserTypeCatalog>("/api/v1/user-types", {
    query: include_retired ? { tenant_id, include_retired: "true" } : { tenant_id },
  });

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
  /**
   * The CALLER'S OWN movement on `wallet_account_id` — never the transaction's
   * headline. A supervisor earning R0.50 of parent commission on a R100
   * cash-in reads R0.50 here.
   */
  amount: string;
  /** The transaction's headline principal, kept separate from `amount`. */
  transaction_amount?: string;
  /**
   * Which of the user's wallets moved. One transaction yields one row PER
   * wallet it touches, so an agent's cash-in produces a main-wallet row for
   * what they paid and a commission-wallet row for what they earned.
   */
  wallet_account_id?: string | null;
  wallet_account_type?: string | null;
  wallet_label?: string | null;
  /** Service charge debited with this transaction. "0" when none applied. */
  fee_amount: string;
  currency: string;
  created_at: string;
  direction: "in" | "out";
  /**
   * The other party's display name — a merchant's business name, else the
   * person's full name. Null when the other side is a system/provider account
   * (funds, reward issuance, redemption), never a service name.
   */
  counterparty_name: string | null;
  /**
   * The two principals, populated ONLY when the user is a THIRD PARTY to the
   * transaction — a supervisor earning parent commission from a transaction
   * between their agent and a customer. Null when the user is one of the sides,
   * where `counterparty_name` already says what they need.
   */
  sender_name?: string | null;
  receiver_name?: string | null;
  /** The same party's phone number. Admin-only — absent from the mobile feed. */
  counterparty_phone: string | null;
}

/**
 * One page of a user's wallet MOVEMENTS, plus the total matching the filters.
 *
 * `total` counts TRANSACTIONS, not rows: a transaction touching two of the
 * user's wallets yields a row each, so `items.length` can exceed the page
 * limit. A footer should read "of N transactions".
 */
export interface UserTransactionsPage {
  items: UserTransaction[];
  total: number;
}

/**
 * One page of a user's transactions. Filtering and paging are SERVER-side so
 * an operator can find a single movement in a long ledger without the page
 * loading it all.
 *
 * @param currency Exact match ("ZAR" / "INR" / "PTS"); omit for all.
 * @param q Case-insensitive substring of the reference (e.g. "S_2026...").
 */
export const listUserTransactions = (
  tenant_id: string,
  user_id: string,
  opts: {
    limit?: number;
    offset?: number;
    currency?: string;
    q?: string;
    /**
     * Restrict to one of the user's wallets. Held commission and spendable
     * money share a currency, so the currency filter alone cannot separate
     * them.
     */
    wallet_type?: string;
  } = {},
) =>
  apiGet<UserTransactionsPage>(
    `/api/v1/identity/users/${user_id}/transactions`,
    {
      query: {
        tenant_id,
        limit: opts.limit ?? 20,
        offset: opts.offset ?? 0,
        ...(opts.currency ? { currency: opts.currency } : {}),
        ...(opts.wallet_type ? { wallet_type: opts.wallet_type } : {}),
        ...(opts.q ? { q: opts.q } : {}),
      },
    },
  );

/**
 * Add an identifier to an existing user (Epic 27, Story 27.2). Admin-added
 * identifiers are stored unverified (not OTP-proven). Backend 409s
 * `identifier_already_in_use` on a duplicate. card_number is not accepted.
 */
export const addUserIdentifier = (
  user_id: string,
  tenant_id: string,
  payload: AddUserIdentifierPayload,
) =>
  apiPost<UserIdentifier>(
    `/api/v1/identity/users/${user_id}/identifiers`,
    payload,
    { query: { tenant_id } },
  );

/**
 * Manually mark an account_number identifier verified (Epic 27, Story 27.3;
 * platform-admin). Phone/email verify via OTP — the backend 422s
 * `identifier_not_manually_verifiable` for those. Already-verified is an
 * idempotent 200. Returns the updated identifier.
 */
export const verifyUserIdentifier = (
  user_id: string,
  identifier_id: string,
  tenant_id: string,
) =>
  apiPost<UserIdentifier>(
    `/api/v1/identity/users/${user_id}/identifiers/${identifier_id}/verify`,
    undefined,
    { query: { tenant_id } },
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
  // Epic 10 / WAL-79 — target only members of this segment (any rule type).
  // Omit to target all users.
  segment_id?: string;
  reward_type: Rule["reward_type"];
  reward_value: string;
  // Financial currency for a cashback reward (3-char ISO 4217). REQUIRED
  // when reward_type === "cashback"; MUST be omitted for points (the
  // backend 422s a currency on a points rule).
  reward_currency?: string;
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
  // Retarget the rule at a segment; an explicit null clears the binding
  // (back to all users). Omit to leave targeting unchanged.
  segment_id?: string | null;
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
  /** Rows to skip — the audit log grows for 7 years, so views page (B7.3). */
  offset?: number;
}

export const queryAuditLog = (q: AuditQuery) =>
  apiGet<AuditEntry[]>("/api/v1/reconciliation/audit", {
    query: {
      tenant_id: q.tenant_id,
      entity_type: q.entity_type,
      entity_id: q.entity_id,
      limit: q.limit,
      offset: q.offset,
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
  limit?: number,
  offset?: number,
  q?: string,
) =>
  apiGet<ConfigChangeRequest[]>("/api/v1/config-requests", {
    query: { tenant_id, status_filter, config_type, limit, offset, q },
  });

/**
 * Cheap per-status counts for the config-requests queue (approvals tab bar).
 * `q` scopes the counts to whole-queue search matches (B7.2c).
 */
export const getConfigRequestCounts = (tenant_id: string, q?: string) =>
  apiGet<QueueCounts>("/api/v1/config-requests/counts", { query: { tenant_id, q } });

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

/** Every points→fiat conversion rate in a tenant (any status) — admin list. */
export const listConversionRates = (tenant_id: string) =>
  apiGet<PointsConversionRate[]>("/api/v1/redemption/conversion-rates/admin", {
    query: { tenant_id },
  });

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

/**
 * Release a user's PIN lockout WITHOUT changing their PIN (platform-admin).
 * Distinct from adminResetPin, which changes the PIN and also unlocks.
 */
export const unlockUser = (user_id: string, tenant_id: string) =>
  apiPost<AdminUnlockResponse>(
    `/api/v1/identity/users/${user_id}/unlock`,
    undefined,
    { query: { tenant_id } },
  );

/**
 * Set a user's admin-imposed access level (platform-admin). `login_locked`
 * kills the user's session; `transactions_locked` blocks transacting;
 * `active` restores full access. Distinct from the PIN lockout above.
 */
export const setUserAccess = (
  user_id: string,
  tenant_id: string,
  level: SettableAccessLevel,
) =>
  apiPost<AdminAccessResponse>(
    `/api/v1/identity/users/${user_id}/access`,
    { level },
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

/**
 * List a tenant's money operations, optionally filtered by lifecycle status and
 * windowed by limit/offset (newest-first; the approvals page fetches one page).
 */
export const listMoneyOperations = (
  tenant_id: string,
  status_filter?: MoneyOperationStatus,
  limit?: number,
  offset?: number,
  q?: string,
) =>
  apiGet<MoneyOperation[]>("/api/v1/money-operations", {
    query: { tenant_id, status_filter, limit, offset, q },
  });

/**
 * Cheap per-status counts for the money-operations queue (approvals tab bar).
 * `q` scopes the counts to whole-queue search matches (B7.2c).
 */
export const getMoneyOperationCounts = (tenant_id: string, q?: string) =>
  apiGet<QueueCounts>("/api/v1/money-operations/counts", { query: { tenant_id, q } });

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

/**
 * List a tenant's user operations, optionally filtered by lifecycle status and
 * windowed by limit/offset (newest-first; the approvals page fetches one page).
 */
export const listUserOperations = (
  tenant_id: string,
  status_filter?: UserOperationStatus,
  limit?: number,
  offset?: number,
  q?: string,
) =>
  apiGet<UserOperation[]>("/api/v1/user-operations", {
    query: { tenant_id, status_filter, limit, offset, q },
  });

/**
 * Cheap per-status counts for the user-operations queue (approvals tab bar).
 * `q` scopes the counts to whole-queue search matches (B7.2c).
 */
export const getUserOperationCounts = (tenant_id: string, q?: string) =>
  apiGet<QueueCounts>("/api/v1/user-operations/counts", { query: { tenant_id, q } });

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
  // Required — every segment belongs to exactly one exclusive-tier group.
  group_id: string;
  name: string;
  description?: string;
  // Within a group the highest matching priority wins. Backend default 0.
  priority?: number;
  // Present + non-null -> dynamic (evaluator-assigned) segment; omitted ->
  // static (admin-assigned), matching today's behaviour.
  criteria?: SegmentCriteriaDoc;
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

/**
 * PATCH payload for `updateSegment` — mirrors the backend's
 * `SegmentUpdateRequest` exactly (Segmentation Phase 1 Task 7/11). Every
 * field is optional; the edit dialog only ever includes a key when that
 * field's value actually changed, so the backend's audit row (which records
 * only the changed fields) stays accurate. `criteria=undefined` (an omitted
 * key) means "leave criteria alone" — turning a dynamic segment back to
 * static requires the explicit `clear_criteria: true` flag, never sending
 * `criteria` and `clear_criteria: true` together (the backend 422s that
 * combination).
 */
export interface UpdateSegmentPayload {
  // Renaming is allowed even for an `is_system` segment — only group moves
  // are blocked for those. Omitting the key leaves the name untouched.
  name?: string;
  // `null` clears the description; omitting the key leaves it untouched.
  description?: string | null;
  group_id?: string;
  priority?: number;
  criteria?: SegmentCriteriaDoc;
  clear_criteria?: boolean;
}

/**
 * Update a segment's description, group, priority, and/or criteria.
 * `tenant_id` is a query param on this route (not part of the JSON body) —
 * see `backend/app/modules/segments/router.py`'s `patch_segment`.
 */
export const updateSegment = (
  segment_id: string,
  tenant_id: string,
  payload: UpdateSegmentPayload,
) =>
  apiPatch<Segment>(`/api/v1/segments/${segment_id}`, payload, {
    query: { tenant_id },
  });

/**
 * Delete a segment. Backend 409s if it's `is_system`-protected or still
 * bound to a rule or bonus multiplier (see `segment_in_use`'s message for
 * which kind and how many).
 */
export const deleteSegment = (segment_id: string, tenant_id: string) =>
  apiDelete<void>(`/api/v1/segments/${segment_id}`, {
    query: { tenant_id },
  });

// ---- Segment groups (the exclusive-tier "lens" a segment belongs to) ----

export interface CreateSegmentGroupPayload {
  tenant_id: string;
  name: string;
  description?: string;
}

export const listSegmentGroups = (tenant_id: string) =>
  apiGet<SegmentGroup[]>("/api/v1/segment-groups", { query: { tenant_id } });

export const createSegmentGroup = (payload: CreateSegmentGroupPayload) =>
  apiPost<SegmentGroup>("/api/v1/segment-groups", payload);

/** Delete a segment group. Backend 409s if it's system-owned or still has segments. */
export const deleteSegmentGroup = (group_id: string, tenant_id: string) =>
  apiDelete<void>(`/api/v1/segment-groups/${group_id}`, {
    query: { tenant_id },
  });

// ---- Dynamic-segment criteria DSL (vocabulary, dry-run preview, recompute) -

/** The criteria DSL's metric vocabulary, sorted by name — drives the criteria builder. */
export const listSegmentMetrics = () =>
  apiGet<SegmentMetricInfo[]>("/api/v1/segments/metrics");

/**
 * Per-segment (manual/criteria split) and per-group (distinct users) member
 * counts for the tenant. A segment or group with zero members is simply
 * absent from its array — the Segments page treats a missing id as 0.
 */
export const getSegmentMemberCounts = (tenant_id: string) =>
  apiGet<MemberCounts>("/api/v1/segments/member-counts", { query: { tenant_id } });

/** Dry-run: count users a not-yet-saved criteria document would currently match. */
export const previewSegmentCriteria = (
  tenant_id: string,
  criteria: SegmentCriteriaDoc,
) =>
  apiPost<{ match_count: number }>("/api/v1/segments/preview", {
    tenant_id,
    criteria,
  });

/**
 * Enqueue an async recompute of every dynamic segment for one tenant.
 * `tenant_id` is a query param on the backend route (no request body).
 */
export const recomputeSegments = (tenant_id: string) =>
  apiPost<{ status: string }>("/api/v1/segments/recompute", undefined, {
    query: { tenant_id },
  });

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
  // Backend requires an Idempotency-Key on this create (Pay-PRD-0200); a
  // fresh UUID per invocation — server-side fetch retries reuse it.
  apiPost<BonusMultiplier>("/api/v1/multipliers", payload, {
    idempotencyKey: crypto.randomUUID(),
  });

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

// ---- Analytics -----------------------------------------------------------

/** The tenant's transacting currencies — drives the dashboard currency toggle. */
export const getCurrencies = (tenant_id: string) =>
  apiGet<CurrencyInfo[]>("/api/v1/analytics/currencies", {
    query: { tenant_id },
  });

export const getAnalyticsSummary = (tenant_id: string, range: AnalyticsRange) =>
  apiGet<DashboardSummary>("/api/v1/analytics/summary", {
    query: { tenant_id, range },
  });

export const getTransactionsTimeseries = (
  tenant_id: string,
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) =>
  apiGet<MetricsTimeseries>("/api/v1/analytics/transactions/timeseries", {
    query: { tenant_id, range, granularity },
  });

export const getTransactionsByService = (tenant_id: string, range: AnalyticsRange) =>
  apiGet<ServiceSlice[]>("/api/v1/analytics/transactions/by-service", {
    query: { tenant_id, range },
  });

export const getTransactionsByStatus = (
  tenant_id: string,
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) =>
  apiGet<StatusBucket[]>("/api/v1/analytics/transactions/by-status", {
    query: { tenant_id, range, granularity },
  });

export const getUsersTimeseries = (
  tenant_id: string,
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) =>
  apiGet<UsersTimeseries>("/api/v1/analytics/users/timeseries", {
    query: { tenant_id, range, granularity },
  });

export const getActiveUsers = (tenant_id: string) =>
  apiGet<ActiveUsers>("/api/v1/analytics/users/active", {
    query: { tenant_id },
  });

export const getRevenueByService = (tenant_id: string, range: AnalyticsRange) =>
  apiGet<RevenueServiceSlice[]>("/api/v1/analytics/revenue/by-service", {
    query: { tenant_id, range },
  });

export const getRewardsTimeseries = (
  tenant_id: string,
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) =>
  apiGet<RewardsTimeseries>("/api/v1/analytics/rewards/timeseries", {
    query: { tenant_id, range, granularity },
  });

export const getLiquidity = (tenant_id: string) =>
  apiGet<CurrencyLiquidity[]>("/api/v1/analytics/liquidity", {
    query: { tenant_id },
  });

export const getNetFlow = (
  tenant_id: string,
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) =>
  apiGet<NetFlowPoint[]>("/api/v1/analytics/net-flow", {
    query: { tenant_id, range, granularity },
  });

export const getUsersByType = (tenant_id: string) =>
  apiGet<UserTypeSlice[]>("/api/v1/analytics/users/by-type", {
    query: { tenant_id },
  });


/**
 * Commission batches (spec 2026-08-26 §8). Upload is multipart, so it does not
 * go through the JSON `apiPost` helper.
 */
export const listCommissionBatches = (
  tenant_id: string,
  params?: { batch_type?: string; status?: string },
) => {
  const query = new URLSearchParams({ tenant_id });
  if (params?.batch_type) query.set("batch_type", params.batch_type);
  if (params?.status) query.set("status", params.status);
  return apiGet<CommissionBatch[]>(`/api/v1/commission-batches?${query}`);
};

export const getCommissionBatch = (tenant_id: string, batch_id: string) =>
  apiGet<CommissionBatch>(
    `/api/v1/commission-batches/${batch_id}?tenant_id=${tenant_id}`,
  );


/** One user who reports to a supervisor. */
export interface UserReport {
  id: string;
  name: string | null;
  user_type: string;
  status: string;
  created_at: string;
  /** Accrued commission per currency — what this child has fed upward. */
  accrued_commission: Record<string, string>;
}

/** One page of a supervisor's downline. */
export interface UserReportsPage {
  items: UserReport[];
  total: number;
}

/**
 * The users reporting to this one. The hierarchy was only readable upwards
 * until now, which left an operator reconciling parent commission unable to
 * see which users fed it.
 */
export const listUserReports = (
  tenant_id: string,
  user_id: string,
  opts: { limit?: number; offset?: number } = {},
) =>
  apiGet<UserReportsPage>(`/api/v1/identity/users/${user_id}/reports`, {
    query: {
      tenant_id,
      limit: opts.limit ?? 50,
      offset: opts.offset ?? 0,
    },
  });
