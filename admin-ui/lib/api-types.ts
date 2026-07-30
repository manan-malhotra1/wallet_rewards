/**
 * TypeScript shapes that mirror the FastAPI Pydantic response models.
 * Keep them in sync — when the backend schema changes, update here too.
 *
 * These are deliberately permissive: any field that's optional in the
 * Pydantic model is `| null | undefined` here so UI code defends against
 * the wire format.
 */

export type BusinessType = "wallet" | "rewards" | "both";

/** The five first-class user types (Epic 12). */
export type UserType =
  | "consumer"
  | "agent"
  | "super_agent"
  | "merchant"
  | "head_merchant";

/** External-API key (Epic 14). The secret is only ever returned once. */
export interface ApiKey {
  id: string;
  tenant_id: string;
  key_id: string;
  label: string | null;
  status: string;
  last_used_at: string | null;
  created_at: string;
  /**
   * When set, the key can call the external merchant cash-in API, funding
   * consumers from this merchant user's wallet. Null → ordinary partner key
   * (fund/withdraw only).
   */
  merchant_user_id: string | null;
}

/** Create response — carries the plaintext secret, shown once and never again. */
export interface ApiKeyCreated extends ApiKey {
  secret: string;
}

export interface Tenant {
  id: string;
  name: string;
  business_type: BusinessType;
  keycloak_realm: string | null;
  base_currency: string | null;
  status: string;
  created_at: string;
  /**
   * Per-tenant runtime branding. All nullable — absence means "fall back to
   * the app default palette / Sasai mark". `brand_accent_color` /
   * `brand_light_color` are hex strings the palette engine derives tokens
   * from; `brand_icon_url` is an http(s) URL for the sidebar brand mark.
   */
  brand_accent_color: string | null;
  brand_light_color: string | null;
  brand_icon_url: string | null;
}

/** The three cosmetic branding fields, read/written via `/branding`. */
export interface TenantBranding {
  brand_accent_color: string | null;
  brand_light_color: string | null;
  brand_icon_url: string | null;
}

/** One row in the per-tenant instruments catalog (Phase 3). */
export interface Instrument {
  id: string;
  tenant_id: string;
  code: string;
  symbol: string;
  display_name: string;
  description: string | null;
  account_type: "financial_wallet" | "points_account";
  status: "active" | "disabled";
  created_at: string;
  updated_at: string;
}

/** One row in the per-tenant services catalog (Phase 2). */
export interface Service {
  id: string;
  tenant_id: string;
  code: string;
  display_name: string;
  description: string | null;
  status: "active" | "disabled";
  created_at: string;
  updated_at: string;
}

export interface User {
  id: string;
  tenant_id: string;
  status: string;
  user_type: UserType;
  parent_user_id: string | null;
  created_at: string;
  identifiers: UserIdentifier[];
}

export interface UserProfile {
  first_name: string | null;
  last_name: string | null;
  date_of_birth: string | null;
}

export interface UserAccount {
  id: string;
  account_type: string;
  currency: string;
  status: string;
  balance: string;
  reserved_balance: string;
  available_balance: string;
}

/**
 * Admin-imposed access restriction level (distinct from the automatic PIN
 * lockout `is_locked`). `login_locked` = user cannot log in (session killed);
 * `transactions_locked` = user can log in but cannot transact; `closed` is a
 * terminal state reflected in the status pill.
 */
export type AccessLevel =
  | "active"
  | "login_locked"
  | "transactions_locked"
  | "closed";

/** The three access levels an admin can set via setUserAccess (not `closed`). */
export type SettableAccessLevel = "active" | "login_locked" | "transactions_locked";

export interface UserDetail {
  id: string;
  tenant_id: string;
  status: string;
  user_type: UserType;
  parent_user_id: string | null;
  /** Resolved parent display name; null when no parent or unresolvable — fall back to a short id. */
  parent_name: string | null;
  created_at: string;
  identifiers: UserIdentifier[];
  profile: UserProfile | null;
  accounts: UserAccount[];
  /** True while the user is PIN-locked (5 failed attempts → 30-min auto-expiring lock). */
  is_locked: boolean;
  /** Remaining lockout TTL in seconds; null when not locked. */
  unlocks_in_seconds: number | null;
  /** Admin-imposed access restriction; separate from the automatic PIN lockout. */
  access_level: AccessLevel;
}

/** Response from the admin set-access endpoint. */
export interface AdminAccessResponse {
  user_id: string;
  status: string;
  level: AccessLevel;
}

export interface UserIdentifier {
  id: string;
  identifier_type: "phone" | "email" | "account_number" | "card_number";
  identifier_value: string;
  verified: boolean;
}

/**
 * Identifier types an admin may add to an existing user (Epic 27, Story 27.2).
 * `card_number` is intentionally excluded — raw PANs require PSP tokenisation
 * (Phase 2) and are never accepted here.
 */
export type AddableIdentifierType = "phone" | "email" | "account_number";

/** Request body for adding an identifier to a user (Epic 27, Story 27.2). */
export interface AddUserIdentifierPayload {
  identifier_type: AddableIdentifierType;
  identifier_value: string;
}

export interface Account {
  id: string;
  tenant_id: string;
  user_id: string | null;
  account_type: string;
  currency: string;
  created_at: string;
}

export interface BalanceResponse {
  account_id: string;
  balance: string;
  reserved_balance: string;
  available_balance: string;
  currency: string;
}

/** Composite operator joining a composite rule's sub-conditions (WAL-75). */
export type CompositeOperator = "AND" | "OR";

/** When a referral rule fires — on signup, or on the referee's Nth txn (WAL-77). */
export type ReferralTrigger = "signup" | "nth_transaction";

/** One sub-condition of a composite rule: a qualifying-txn count (WAL-75). */
export interface RuleCondition {
  transaction_type: string;
  count_threshold: number;
  min_amount?: string | null;
  sort_order?: number;
}

export interface Rule {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  rule_type:
    | "milestone"
    | "streak"
    | "first_time"
    | "value_based"
    | "composite"
    | "campaign"
    | "referral";
  transaction_type: string | null;
  count_threshold: number | null;
  min_amount: string | null;
  time_window: string | null;
  // Epic 10 — rule-type-specific fields. Null for rule types that
  // don't use them.
  streak_units: number | null;
  streak_unit_window: "day" | "week" | null;
  campaign_start_date: string | null;
  campaign_end_date: string | null;
  // Epic 10 / WAL-75 — composite operator + sub-conditions.
  composite_operator?: CompositeOperator | null;
  conditions?: RuleCondition[] | null;
  // Epic 10 / WAL-77 — referral trigger + optional referee (new-joiner)
  // reward. The referrer reward reuses reward_type/reward_value.
  referral_trigger?: ReferralTrigger | null;
  referral_trigger_n?: number | null;
  referee_reward_value?: string | null;
  reward_type: "points" | "cashback";
  reward_value: string;
  stop_after_n_triggers: number | null;
  resets_after_trigger: boolean;
  status: string;
  created_at: string;
}

/**
 * Campaign (rule) performance metrics — backend computes these from
 * `reward_events`. Surfaces on the campaigns list as Fires + Unique
 * users columns, and on the campaign detail drawer.
 */
export interface RulePerformance {
  rule_id: string;
  total_fires: number;
  unique_users_rewarded: number;
  total_reward_value: string;
  first_fired_at: string | null;
  last_fired_at: string | null;
  budget_scope: "none" | "tenant_only" | "rule_only" | "both";
}

/**
 * Per-(tenant, transaction_type, currency) PIN step-up threshold.
 * Transactions exceeding `threshold_amount` require the user to
 * re-enter their PIN.
 */
export interface StepUpPolicy {
  id: string;
  tenant_id: string;
  transaction_type: string;
  currency: string;
  threshold_amount: string;
  created_at: string;
  updated_at: string;
}

/** Admin-triggered PIN reset response. */
export interface AdminPinResetResponse {
  user_id: string;
  delivered_via: "inline" | "sms";
  new_pin: string | null;
}

/** Admin-triggered PIN-lockout release response (does not change the PIN). */
export interface AdminUnlockResponse {
  user_id: string;
  was_locked: boolean;
}

/** A static user cohort (Epic 10 / WAL-79). */
export interface Segment {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

/** A reward-amplifying multiplier (Epic 10 / WAL-78). */
export interface BonusMultiplier {
  id: string;
  tenant_id: string;
  rule_id: string | null;
  segment_id: string | null;
  multiplier: string;
  valid_from: string | null;
  valid_until: string | null;
  created_at: string;
}

/** A system-owned account (user_id IS NULL) with its derived balance. */
export interface SystemWallet {
  id: string;
  tenant_id: string;
  account_type: string;
  currency: string;
  status: string;
  balance: string;
  created_at: string;
  /** Operator-chosen label; populated for bank mirrors (operator_adjustment), null otherwise. */
  name: string | null;
}

/** One row in the system-wallet transactions drill-down. */
export interface SystemWalletTransaction {
  transaction_id: string;
  /** Customer-facing reference S_<datetime><seq>; null for un-backfilled legacy rows. */
  reference: string | null;
  transaction_type: string;
  status: string;
  entry_type: "DEBIT" | "CREDIT";
  entry_amount: string;
  currency: string;
  created_at: string;
}

export interface FundUserResponse {
  transaction_id: string;
  user_id: string;
  amount: string;
  currency: string;
  new_balance: string;
}

export interface AdjustSystemWalletResponse {
  transaction_id: string;
  account_id: string;
  amount: string; // signed
  currency: string;
  new_balance: string;
}

export interface RedemptionProvider {
  id: string;
  tenant_id: string;
  name: string;
  redemption_wallet_account_id: string;
  status_check_url: string | null;
  max_retries: number;
  retry_interval_secs: number;
  escalate_after_mins: number;
  status: string;
}

export interface Redemption {
  id: string;
  tenant_id: string;
  user_id: string;
  provider_id: string;
  transaction_id: string;
  points_amount: string;
  status: string;
  external_reference: string | null;
  failure_reason: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ExternalEventSource {
  id: string;
  tenant_id: string;
  name: string;
  source_key: string;
  status: string;
}

export interface AuditEntry {
  id: string;
  tenant_id: string | null;
  actor_id: string;
  actor_type: "user" | "admin" | "system";
  /** Resolved actor display name; "System" for system actors, null when unresolvable. */
  actor_name: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  /** Affected user's display name when entity_type === "user"; null otherwise. */
  entity_name: string | null;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  ip_address: string | null;
  note: string | null;
  created_at: string;
}

export interface PendingItem {
  redemption_id: string;
  tenant_id: string;
  amount: string;
  age_minutes: number;
  retry_count: number;
  status: string;
}

export interface ManualReviewItem {
  redemption_id: string;
  tenant_id: string;
  user_id: string;
  /** Resolved user display name; null when unresolvable — fall back to a short id. */
  user_name: string | null;
  amount: string;
  retry_count: number;
  failure_reason: string | null;
}

export interface SweepOutcome {
  scanned_count: number;
  bumped_count: number;
  escalated_count: number;
  audit_entry_count: number;
}

export interface Role {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  status: string;
  created_at: string;
}

// ---- Phase G — Money Controls --------------------------------------------

export interface LimitConfig {
  id: string;
  tenant_id: string;
  transaction_type: string;
  account_type: string;
  currency: string;
  user_type: UserType | null;
  min_amount: string | null;
  max_amount: string | null;
  daily_count_cap: number | null;
  daily_value_cap: string | null;
  weekly_count_cap: number | null;
  weekly_value_cap: string | null;
  monthly_count_cap: number | null;
  monthly_value_cap: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Per-(tenant, currency) financial-wallet limit config (WAL-236): a max-balance
 * ceiling plus cumulative send + receive count/value caps across rolling
 * daily/weekly/monthly windows. Every cap is nullable (null = no limit).
 */
export interface WalletLimitConfig {
  id: string;
  tenant_id: string;
  currency: string;
  user_type: UserType | null;
  max_balance: string | null;
  send_daily_count_cap: number | null;
  send_daily_value_cap: string | null;
  send_weekly_count_cap: number | null;
  send_weekly_value_cap: string | null;
  send_monthly_count_cap: number | null;
  send_monthly_value_cap: string | null;
  receive_daily_count_cap: number | null;
  receive_daily_value_cap: string | null;
  receive_weekly_count_cap: number | null;
  receive_weekly_value_cap: string | null;
  receive_monthly_count_cap: number | null;
  receive_monthly_value_cap: string | null;
  created_at: string;
  updated_at: string;
}

export interface PricingConfig {
  id: string;
  tenant_id: string;
  transaction_type: string;
  account_type: string;
  currency: string;
  user_type: UserType | null;
  fixed_fee: string;
  variable_fee_pct: string;
  fee_cap: string | null;
  // Pricing v2 (Epic 24) — optional slab band + fee-inclusive flag.
  // Null band ends mean "applies to all amounts" on that side.
  amount_from: string | null;
  amount_to: string | null;
  fee_inclusive: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Per-(tenant, transaction_type, currency, user_type) commission config
 * (Epic 24 / Story 24.2). Commission is what the platform pays out (agent
 * incentive) rather than what it charges. All money fields are decimal
 * strings on the wire; `amount_from`/`amount_to` define an optional slab
 * band (null = unbounded on that side).
 */
export interface CommissionConfig {
  id: string;
  tenant_id: string;
  transaction_type: string;
  currency: string;
  user_type: UserType | null;
  amount_from: string | null;
  amount_to: string | null;
  fixed_commission: string;
  variable_commission_pct: string;
  commission_cap: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Per-(tenant, currency) tax config (Epic 24 / Story 24.2). Applies a tax
 * rate to fees and commissions independently, each with its own
 * inclusive/exclusive flag. Keyed only by currency — no service/user_type.
 */
export interface TaxConfig {
  id: string;
  tenant_id: string;
  currency: string;
  fee_tax_pct: string;
  commission_tax_pct: string;
  fee_tax_inclusive: boolean;
  commission_tax_inclusive: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * A pricing CONFIG grouped by scope (Epic 25 Pass 1). The flat
 * `listPricingConfigs` rows are grouped by (transaction_type, account_type,
 * currency, user_type) into one config per scope; its bands are the flat rows
 * that share that scope, sorted by `amount_from` (nulls last). The table shows
 * one row per group; bands render inside the View / Edit surfaces.
 */
export interface PricingConfigGroup {
  /** Stable scope key, e.g. `cash_in|financial_wallet|ZAR|all`. */
  key: string;
  transaction_type: string;
  account_type: string;
  currency: string;
  user_type: UserType | null;
  fee_inclusive: boolean;
  bands: PricingConfig[];
}

/**
 * A commission CONFIG grouped by scope (Epic 25 Pass 1). Same shape as
 * `PricingConfigGroup` but keyed by (transaction_type, currency, user_type) —
 * commissions carry no account_type / fee-inclusive leg.
 */
export interface CommissionConfigGroup {
  /** Stable scope key, e.g. `cash_in|ZAR|agent`. */
  key: string;
  transaction_type: string;
  currency: string;
  user_type: UserType | null;
  bands: CommissionConfig[];
}

// ---- Epic 24 — maker-checker config changes -----------------------------

/** The config domains that flow through the maker-checker pipeline. */
export type ConfigType =
  | "pricing"
  | "limit"
  | "wallet_limit"
  | "commission"
  | "tax"
  | "step_up";

/**
 * The mutation a change request proposes. An `update` re-proposes a live
 * config's values in place (scope unchanged), carrying the create-shaped
 * payload plus the `target_config_id` of the row being edited.
 */
export type ConfigOperation = "create" | "update" | "delete";

/** Lifecycle status of a config change request. */
export type ConfigRequestStatus =
  | "PENDING"
  | "CHANGES_REQUESTED"
  | "APPLIED"
  | "WITHDRAWN";

/**
 * Action recorded on a single review entry. Values mirror the backend
 * review verbs. Kept as a union for display switching; render defensively
 * since the backend owns the canonical set.
 * TODO(Epic 24): confirm exact casing/values against the backend enum.
 */
// Backend review-action values (lowercase; see config_requests model).
export type ConfigReviewAction =
  | "submitted"
  | "changes_requested"
  | "revised"
  | "resubmitted"
  | "approved"
  | "withdrawn";

/**
 * One historical revision of a change request's proposed payload. The detail
 * endpoint (`GET /config-requests/{id}`) returns these ascending by revision;
 * the list endpoint does not. Lets maker + checker inspect any past version.
 */
export interface ConfigRevision {
  revision: number;
  payload: Record<string, unknown> | null;
  created_at: string;
}

/** One entry in a change request's review thread. */
export interface ConfigReview {
  id: string;
  actor_admin_id: string;
  /** Resolved display name for the actor (null if not yet recorded). */
  actor_admin_name: string | null;
  actor_role: string;
  action: ConfigReviewAction | string;
  comment: string | null;
  created_at: string;
}

/**
 * A proposed configuration change awaiting a second admin's approval
 * (maker-checker). `payload` carries the create schema for create ops;
 * `target_config_id` names the row to remove for delete ops.
 */
export interface ConfigChangeRequest {
  id: string;
  tenant_id: string;
  config_type: ConfigType;
  operation: ConfigOperation;
  payload: Record<string, unknown> | null;
  target_config_id: string | null;
  status: ConfigRequestStatus;
  maker_admin_id: string;
  /** Resolved display name for the maker (null if not yet recorded). */
  maker_admin_name: string | null;
  checker_admin_id: string | null;
  /** Resolved display name for the checker (null until approved/reviewed). */
  checker_admin_name: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  reviews: ConfigReview[];
  /**
   * Per-revision payload snapshots, ascending. Present only on the single-request
   * detail endpoint (`getConfigRequest`), absent on the list endpoint.
   */
  revisions?: ConfigRevision[];
  /**
   * True only for the read-time "current" baseline the history endpoint
   * synthesizes for a scope with no applied maker-checker history (e.g. a
   * seed-created config). Its `id` is the live config row's id, NOT a real
   * request id — never fetch `GET /config-requests/{id}` for it. Rendered as
   * "Current (baseline)" and never offered for restore (it already is current).
   */
  synthesized?: boolean;
}

// ---- Epic 18 — Money operations (maker-checker for treasury moves) ------

/**
 * The four treasury money movements that flow through N-eyes maker-checker.
 * Values mirror the backend `MONEY_OP_*` constants (see
 * `backend/app/shared/models/money_operations.py`).
 */
export type MoneyOperationType =
  | "fund_user"
  | "withdraw_user"
  | "adjust_system_wallet"
  | "create_bank_mirror";

/** Lifecycle status of a money operation. Mirrors the config-request set. */
export type MoneyOperationStatus =
  | "PENDING"
  | "CHANGES_REQUESTED"
  | "APPLIED"
  | "WITHDRAWN";

/**
 * Action recorded on one review-thread entry. Kept as a permissive union —
 * the backend owns the canonical verbs; render defensively.
 */
export type MoneyOperationReviewAction =
  | "submitted"
  | "changes_requested"
  | "revised"
  | "resubmitted"
  | "approved"
  | "withdrawn";

/** One entry in a money operation's append-only review thread. */
export interface MoneyOperationReview {
  id: string;
  actor_admin_id: string;
  /** Resolved display name for the actor (null if not yet recorded). */
  actor_admin_name: string | null;
  actor_role: string;
  action: MoneyOperationReviewAction | string;
  comment: string | null;
  created_at: string;
}

/**
 * A proposed treasury money movement awaiting N distinct checker approvals
 * (maker-checker). `payload` carries the operation-specific fields; N-eyes
 * progress is `approvals_count` / `required_approvals`.
 */
export interface MoneyOperation {
  id: string;
  tenant_id: string;
  operation: MoneyOperationType;
  payload: Record<string, unknown>;
  status: MoneyOperationStatus;
  maker_admin_id: string;
  /** Resolved display name for the maker (null if not yet recorded). */
  maker_admin_name: string | null;
  required_approvals: number;
  approvals_count: number;
  applied_transaction_id: string | null;
  created_at: string;
  updated_at: string;
  reviews: MoneyOperationReview[];
  /** Resolved user name for fund_user/withdraw_user (null if unresolvable). */
  subject_name: string | null;
  /** Resolved target system-account name for adjust_system_wallet. */
  account_name: string | null;
  /** Resolved bank-mirror account name (adjust_system_wallet/withdraw_user). */
  bank_mirror_name: string | null;
}

// ---- Epic 3 — User operations (create/edit user maker-checker) -----------

/** The admin user operations that flow through N-eyes maker-checker. */
export type UserOperationType = "create_user" | "update_user";

/** Lifecycle status of a user operation. Mirrors the money-operation set. */
export type UserOperationStatus =
  | "PENDING"
  | "CHANGES_REQUESTED"
  | "APPLIED"
  | "WITHDRAWN";

/**
 * Action recorded on one review-thread entry. Permissive union — the backend
 * owns the canonical verbs; render defensively.
 */
export type UserOperationReviewAction =
  | "submitted"
  | "changes_requested"
  | "revised"
  | "resubmitted"
  | "approved"
  | "withdrawn";

/** One entry in a user operation's append-only review thread. */
export interface UserOperationReview {
  id: string;
  actor_admin_id: string;
  /** Resolved display name for the actor (null if not yet recorded). */
  actor_admin_name: string | null;
  actor_role: string;
  action: UserOperationReviewAction | string;
  comment: string | null;
  created_at: string;
}

/** A user-operation request, with its review thread + N-eyes progress. */
export interface UserOperation {
  id: string;
  tenant_id: string;
  operation: UserOperationType;
  payload: Record<string, unknown>;
  status: UserOperationStatus;
  maker_admin_id: string;
  /** Resolved display name for the maker (null if not yet recorded). */
  maker_admin_name: string | null;
  required_approvals: number;
  approvals_count: number;
  /** The user created/edited once the operation applied (null before then). */
  applied_user_id: string | null;
  created_at: string;
  updated_at: string;
  reviews: UserOperationReview[];
  /** For update_user: the edited user's current display name (null if none). */
  target_name: string | null;
}

export interface RewardBudget {
  id: string;
  tenant_id: string;
  scope_type: "tenant" | "rule";
  scope_id: string | null;
  currency: string;
  window_type: "rolling_24h" | "rolling_7d" | "calendar_month" | "lifetime";
  cap_amount: string;
  status: "active" | "paused";
  created_at: string;
  updated_at: string;
}

export interface BudgetConsumption {
  budget: RewardBudget;
  consumed_amount: string;
  remaining_amount: string;
  percent_consumed: number;
}
