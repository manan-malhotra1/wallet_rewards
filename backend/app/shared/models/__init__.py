"""SQLAlchemy ORM models.

Import every model here so Alembic autogenerate sees them via Base.metadata,
and so callers can `from app.shared.models import Tenant, User, ...`.
"""
from app.shared.models.accounts import (
    ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_PROVIDER_REDEMPTION,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    ACCOUNT_TYPES,
    Account,
    AccountBalanceSnapshot,
)
from app.shared.models.budgets import (
    BUDGET_SCOPE_RULE,
    BUDGET_SCOPE_TENANT,
    BUDGET_STATUS_ACTIVE,
    BUDGET_STATUS_PAUSED,
    BUDGET_WINDOW_CALENDAR_MONTH,
    BUDGET_WINDOW_LIFETIME,
    BUDGET_WINDOW_ROLLING_7D,
    BUDGET_WINDOW_ROLLING_24H,
    RewardBudget,
)
from app.shared.models.limits import LimitConfig, WalletLimitConfig
from app.shared.models.multipliers import BonusMultiplier
from app.shared.models.pricing import PricingConfig
from app.shared.models.instruments import (
    INSTRUMENT_STATUS_ACTIVE,
    INSTRUMENT_STATUS_DISABLED,
    Instrument,
)
from app.shared.models.segments import Segment, UserSegment
from app.shared.models.services import (
    SERVICE_STATUS_ACTIVE,
    SERVICE_STATUS_DISABLED,
    Service,
)
from app.shared.models.step_up import StepUpPolicy
from app.shared.models.audit import (
    ACTION_RECON_ESCALATED,
    ACTION_RECON_RESOLVED_COMPLETED,
    ACTION_RECON_RESOLVED_REVERSED,
    ACTION_RECON_SWEPT,
    ACTOR_ADMIN,
    ACTOR_SYSTEM,
    ACTOR_USER,
    AuditLog,
)
from app.shared.models.base import Base
from app.shared.models.events import (
    INGESTION_STATUS_DUPLICATE,
    INGESTION_STATUS_FAILED,
    INGESTION_STATUS_PROCESSED,
    INGESTION_STATUS_REJECTED,
    EventIngestionLog,
    ExternalEventSource,
)
from app.shared.models.ledger import (
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    ENTRY_STATUS_PENDING,
    ENTRY_STATUS_REVERSED,
    TXN_STATUS_COMPLETED,
    TXN_STATUS_FAILED,
    TXN_STATUS_PENDING,
    TXN_STATUS_REVERSED,
    LedgerEntry,
    Transaction,
)
from app.shared.models.redemption import (
    REDEMPTION_STATUS_COMPLETED,
    REDEMPTION_STATUS_FAILED,
    REDEMPTION_STATUS_MANUAL_REVIEW,
    REDEMPTION_STATUS_PENDING,
    REDEMPTION_STATUS_PROCESSING,
    REDEMPTION_STATUS_REVERSED,
    REDEMPTION_TERMINAL_STATUSES,
    Redemption,
    RedemptionProvider,
)
from app.shared.models.rewards import RewardEvent
from app.shared.models.roles import (
    ROLE_STATUS_ACTIVE,
    ROLE_STATUS_INACTIVE,
    Role,
    RolePermission,
    UserRole,
)
from app.shared.models.rules import (
    PROGRESS_STATUS_ACTIVE,
    PROGRESS_STATUS_COMPLETED,
    PROGRESS_STATUS_DEACTIVATED,
    REWARD_TYPE_CASHBACK,
    REWARD_TYPE_POINTS,
    RULE_TYPE_CAMPAIGN,
    RULE_TYPE_COMPOSITE,
    RULE_TYPE_FIRST_TIME,
    RULE_TYPE_MILESTONE,
    RULE_TYPE_REFERRAL,
    RULE_TYPE_STREAK,
    RULE_TYPE_VALUE_BASED,
    RULE_TYPES,
    Rule,
    RuleCondition,
    UserRuleProgress,
)
from app.shared.models.tenants import Tenant, TenantConfig
from app.shared.models.users import (
    AuthAttempt,
    OtpRequest,
    User,
    UserIdentifier,
    UserProfile,
)

__all__ = [
    # Base
    "Base",
    # Tenants
    "Tenant",
    "TenantConfig",
    # Users
    "User",
    "UserIdentifier",
    "UserProfile",
    "OtpRequest",
    "AuthAttempt",
    # Accounts
    "Account",
    "AccountBalanceSnapshot",
    "ACCOUNT_TYPE_AIRTIME_MERCHANT_HOLDING",
    "ACCOUNT_TYPE_FINANCIAL_WALLET",
    "ACCOUNT_TYPE_OPERATOR_ADJUSTMENT",
    "ACCOUNT_TYPE_POINTS",
    "ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE",
    "ACCOUNT_TYPE_PROVIDER_REDEMPTION",
    "ACCOUNT_TYPE_SYSTEM_CASH_INFLOW",
    "ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED",
    "ACCOUNT_TYPES",
    # Money controls (Phase G)
    "RewardBudget",
    "LimitConfig",
    "WalletLimitConfig",
    "PricingConfig",
    "StepUpPolicy",
    "Segment",
    "UserSegment",
    "BonusMultiplier",
    # Services catalog (Phase 2)
    "Service",
    "SERVICE_STATUS_ACTIVE",
    "SERVICE_STATUS_DISABLED",
    # Instruments catalog (Phase 3)
    "Instrument",
    "INSTRUMENT_STATUS_ACTIVE",
    "INSTRUMENT_STATUS_DISABLED",
    "BUDGET_SCOPE_TENANT",
    "BUDGET_SCOPE_RULE",
    "BUDGET_STATUS_ACTIVE",
    "BUDGET_STATUS_PAUSED",
    "BUDGET_WINDOW_ROLLING_24H",
    "BUDGET_WINDOW_ROLLING_7D",
    "BUDGET_WINDOW_CALENDAR_MONTH",
    "BUDGET_WINDOW_LIFETIME",
    # Ledger
    "Transaction",
    "LedgerEntry",
    "TXN_STATUS_PENDING",
    "TXN_STATUS_COMPLETED",
    "TXN_STATUS_FAILED",
    "TXN_STATUS_REVERSED",
    "ENTRY_DEBIT",
    "ENTRY_CREDIT",
    "ENTRY_STATUS_PENDING",
    "ENTRY_STATUS_COMPLETED",
    "ENTRY_STATUS_REVERSED",
    # Rules
    "Rule",
    "RuleCondition",
    "UserRuleProgress",
    "RULE_TYPE_MILESTONE",
    "RULE_TYPE_STREAK",
    "RULE_TYPE_FIRST_TIME",
    "RULE_TYPE_VALUE_BASED",
    "RULE_TYPE_COMPOSITE",
    "RULE_TYPE_CAMPAIGN",
    "RULE_TYPE_REFERRAL",
    "RULE_TYPES",
    "REWARD_TYPE_POINTS",
    "REWARD_TYPE_CASHBACK",
    "PROGRESS_STATUS_ACTIVE",
    "PROGRESS_STATUS_COMPLETED",
    "PROGRESS_STATUS_DEACTIVATED",
    # Rewards
    "RewardEvent",
    # Events
    "ExternalEventSource",
    "EventIngestionLog",
    "INGESTION_STATUS_PROCESSED",
    "INGESTION_STATUS_DUPLICATE",
    "INGESTION_STATUS_FAILED",
    "INGESTION_STATUS_REJECTED",
    # Redemption
    "RedemptionProvider",
    "Redemption",
    "REDEMPTION_STATUS_PENDING",
    "REDEMPTION_STATUS_PROCESSING",
    "REDEMPTION_STATUS_COMPLETED",
    "REDEMPTION_STATUS_FAILED",
    "REDEMPTION_STATUS_REVERSED",
    "REDEMPTION_STATUS_MANUAL_REVIEW",
    "REDEMPTION_TERMINAL_STATUSES",
    # Platform roles (Module 7)
    "Role",
    "RolePermission",
    "UserRole",
    "ROLE_STATUS_ACTIVE",
    "ROLE_STATUS_INACTIVE",
    # Audit
    "AuditLog",
    "ACTOR_USER",
    "ACTOR_ADMIN",
    "ACTOR_SYSTEM",
    "ACTION_RECON_SWEPT",
    "ACTION_RECON_ESCALATED",
    "ACTION_RECON_RESOLVED_COMPLETED",
    "ACTION_RECON_RESOLVED_REVERSED",
]
