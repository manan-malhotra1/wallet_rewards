# Sasai Fintech — Wallet & Rewards Platform
## Product Requirements Document

**Project**: Pay & Rewards Platform
**Module**: Core Platform
**Version**: 1.4
**Status**: As-built — reflects platform through 2026-08-05
**Prepared by**: Manan — Sasai Fintech
**Date**: August 2026 (v1.4) — originally May 2026 (v1.3)
**Classification**: Confidential

**Changelog** — v1.4 (2026-08-05): augmented in place to reflect the as-built platform. Added self-registration, the five user types and maker-checker governance, expanded account-type and ledger-guard requirements, the agent cash-in / cash-out / airtime / treasury / partner-API money paths, type-aware limits and pricing, config maker-checker, deployment-mode-gated rewards, reward idempotency and budgets, tenant provisioning / branding / analytics, and the mobile rewards surface. **Every original v1.3 requirement ID is preserved unchanged**; new requirements occupy the numbering gaps within each module. Implementation mechanics live in `docs/design/`; this document remains WHAT-not-HOW.

---

## 1. Purpose

Sasai Fintech operates a remittance business serving diaspora communities across multiple markets. Users who send money home today interact with Sasai at the point of transaction and then disengage — there is no mechanism to hold value within the Sasai ecosystem, no reason to return between remittances, and no way to reward loyalty or deepen the relationship beyond the transfer itself.

This platform changes that. It introduces two complementary capabilities that can be deployed independently or together.

The first is a **wallet** — a stored value account that allows users to receive, hold, and spend money within the Sasai ecosystem. Rather than a remittance arriving directly in a recipient's mobile money account and disappearing, it can land in a Sasai wallet, be held, and be used for everyday transactions: paying bills, sending money to family, topping up services. The wallet transforms Sasai from a one-directional transfer corridor into a financial home for the user.

The second is a **rewards and engagement engine** — a rule-based system that observes transaction activity, whether originating inside the Sasai platform or arriving as events from external partner systems, and rewards users for the behaviours that matter: sending money regularly, paying bills, maintaining streaks, referring friends. Rewards are issued as points, cashback, or tier upgrades. The engine can be deployed as part of the wallet or as a standalone service on top of any external transaction system, making it a reusable capability across Sasai's product portfolio.

Together these capabilities address the core strategic problem: Sasai users are transient. They arrive to send money and leave. The platform gives them a reason to stay.

---

## 2. Problem Statement

Sasai's remittance business generates a transaction at the point of send. That transaction flows to the recipient and the relationship ends. There is no persistent user account on the recipient side, no stored value, no loyalty programme, and no mechanism to re-engage a user between remittance cycles. This creates five compounding problems.

**Users have no reason to hold value with Sasai.** Remittance recipients receive funds into a third-party mobile money account. Sasai has no visibility of what happens next and no opportunity to serve the user's day-to-day financial needs. Every transaction that happens outside Sasai is a missed relationship.

**There is no reward for loyalty.** A user who sends money every week for three years receives the same experience as a first-time user. There is no recognition, no accumulation of value, and no incentive to choose Sasai over a competitor offering a marginally better rate on a given day. Loyalty is invisible to the platform.

**Partner ecosystems cannot leverage Sasai's engagement layer.** When Sasai operates as a white-label or partner-embedded service, there is no way for a partner to trigger rewards based on transactions happening in their own system. Each partner must build their own loyalty logic. There is no shared, configurable engine that can sit across multiple transaction sources.

**Re-engagement is entirely outbound and manual.** When a user goes dormant, the only tool available is a generic marketing message with no context about what the user did, what they were close to earning, or what would bring them back. There is no platform-side awareness of user progress, streaks broken, or milestones missed.

**Multi-product expansion has no shared identity or rewards layer.** As Sasai expands into insurance, savings, and other financial products, each product starts from scratch on user identity and engagement. There is no common foundation that links a user's activity across products or rewards them for engaging with the broader Sasai ecosystem.

The Wallet and Rewards Platform directly resolves each of these. It gives users a financial home within Sasai, makes loyalty visible and rewarding, provides a reusable engagement engine that any partner or internal product can connect to, and gives the re-engagement tooling (via WebEngage) the behavioural data it needs to intervene at the right moment with the right message.

---


## 3. Glossary

| Term | Definition |
|---|---|
| Wallet | A stored value account (SVA) held by a user within the platform, capable of holding a financial balance in a defined currency. |
| Points account | A non-financial account that holds reward points earned by a user through qualifying transaction activity. |
| Tenant | A logical deployment of the platform configured for a specific product line or market. A single user may have accounts across multiple tenants. |
| User | A natural person registered on the platform, identified by a canonical `user_id`. |
| User type | The classification of a user driving type-aware pricing, limits, and hierarchy: consumer, agent, super_agent, merchant, or head_merchant. Agents parent to super-agents, merchants to head-merchants, within one tenant. |
| Merchant | A business entity registered on the platform, capable of receiving payments from users. Realised as a `merchant`/`head_merchant` user type that collects funds into a collection account. |
| Identity resolution | The process of mapping any presented identifier (phone number, email, account number, bank card number) to a canonical `user_id`. |
| Account | A financial or points-holding record linked to a user within a tenant. One user may hold multiple accounts (e.g. a mobile wallet account and a rewards account). |
| Transaction | Any movement of value between accounts — including P2P transfers, bill payments, top-ups, redemptions, and reward credits. |
| P2P transfer | A peer-to-peer transfer of funds between two user wallets. |
| Ledger entry | An immutable, append-only record of a debit or credit applied to an account. The current balance of an account is derived from the sum of its ledger entries. |
| Ledger status | The lifecycle state of a transaction: PENDING, COMPLETED, FAILED, or REVERSED. |
| Reserved balance | The portion of a wallet balance that has been earmarked against an in-progress transaction and is unavailable for new transactions. |
| Available balance | The wallet balance minus any reserved balance. Available balance is the figure presented to users and used for transaction eligibility checks. |
| Deployment mode / business_type | The product configuration of a tenant — `wallet` (money movement, no rewards), `rewards` (rules engine and points ledger only, driven by external events, no financial ledger), or `both` (internal wallet activity drives rewards). |
| Cash float | The operator liquidity account (one per tenant and currency) from which user wallets are funded. Overdraft-floored: it must be pre-funded from the bank before it can fund users. |
| Max balance | The configured ceiling a user financial wallet may hold, enforced on credits at the ledger. Reversals and earned payouts are exempt. |
| Maker-checker (four-eyes / N-eyes) | Governance in which a maker proposes a change and one (four-eyes) or more distinct checkers (N-eyes) approve it before it applies. No self-approval. |
| Step-up PIN | A re-authentication challenge required when a transaction exceeds a configured threshold. Fail-closed: with no policy configured, a PIN is required. |
| Idempotency key | A unique identifier generated per transaction request, used to ensure that duplicate submissions produce the same result without double-processing. |
| Rules engine | The component responsible for evaluating configured transaction rules and determining whether a reward should be issued. |
| Rule / Campaign | A configured reward condition. "Campaign" is the operator-facing label for a rule. |
| User rule progress | A per-user, per-rule record tracking the current count of qualifying transactions and the number of times a rule has fired. |
| Reward | A credit issued to a user's points account or financial wallet when a rule condition is met. |
| Reward event | The record of a single reward firing, made at-most-once per (user, rule, triggering event). |
| Redemption | The process by which a user converts points into cash value, resulting in a transfer from the user's points account to a provider redemption wallet. |
| Provider redemption wallet | A platform-held wallet belonging to a redemption partner, used as the destination for point transfers during the redemption flow. |
| External event | A transaction event originating from a system outside the platform, delivered via an event stream, consumed by the platform for rule evaluation. |
| Event normaliser | The component that maps both internal and external transaction events into a standard schema before passing them to the rules engine. |
| Outbox | A transactional record written alongside a wallet posting (in `both` mode) that decouples wallet activity from reward issuance without external messaging on the hot path. |
| Proof of origin (HMAC) | The signature every external event and provider callback must carry; verified server-side, with failures rejected and audit-logged. |
| PIN | A 4–6 digit personal identification number used to authenticate a user initiating a transaction via USSD or mobile app. |
| OTP | A one-time password sent to a user's registered phone number, used during registration and initial authentication on the mobile app channel. |
| Referral code | A per-user code minted at account creation; attribution is recorded only when a code is supplied at self-registration. |
| Channel | A user-facing access method — USSD, mobile app, or partner API. |
| Reconciliation job | An automated background process that sweeps PENDING transactions older than a configured threshold and resolves them based on external system status. |
| Milestone rule | A rule that fires once a user reaches a defined transaction count threshold, then resets the counter so the same threshold can be reached again. |
| Stop-after-n-triggers | A rule configuration option that deactivates a rule after it has fired a defined number of times for a specific user. When null, the rule fires indefinitely. |
| Streak rule | A rule type that requires a user to complete a qualifying transaction in each consecutive time unit (e.g. weekly) within a defined sequence. Missing any unit resets the streak counter. |
| First-time rule | A rule type that fires exactly once per user — on the first occurrence of a qualifying event. Subsequent occurrences are ignored for that rule. |
| Value-based condition | An additional rule filter requiring a transaction to meet a minimum amount before it is counted toward a rule's threshold. |
| Campaign rule | A rule with a configured active date range. Events outside the range do not contribute to progress and the rule auto-deactivates when the end date passes. |
| Referral rule | A rule that fires a reward for a referring user when a referred user completes a qualifying action. Triggered by the referred user's event, not the referral share. |
| Bonus multiplier | A time-limited configuration that multiplies the points value of all rewards issued during an active period by a configured factor. |
| Audience segment | A named group of users bound to a rule. Only users in the segment are eligible for progress tracking and reward issuance under that rule. |
| Uploaded list segment | An audience segment defined by a file of user IDs or phone numbers uploaded by an Administrator. |
| Behaviour-based segment | An audience segment defined by configurable conditions against user activity data, evaluated at event time rather than pre-computed. |
| Rewards catalog | A user-facing view showing their full rewards journey: points balance, tier status, earned badges, active challenges, redemption history, expiry notices, and next milestone nudges. |
| Next milestone nudge | A dynamically computed prompt shown to a user indicating how many qualifying actions remain before their next rule reward fires. |
| Badge | A non-monetary recognition item awarded to a user when a defined achievement condition is met. Badges are visible in the rewards catalog and never expire. |
| Challenge | A time-limited reward opportunity presented to a user, requiring completion of a defined set of actions within a deadline to earn a reward. |
| Points expiry | A configured rule by which points earned in a period become invalid after a defined duration if not redeemed. |
| External engagement event | A platform-emitted event intended solely for consumption by external engagement tools such as WebEngage. These events carry no platform action and are informational only. |
| Budget | A configured cap on reward issuance per scope (tenant or rule) and window; checked before any reward credit. |

---

## 4. Goals

| Goal ID | Description | Success Indicator |
|---|---|---|
| G1 | Users can register, authenticate, and manage their identity across phone, email, account number, and card identifiers — with a single canonical identity resolving all aliases. | A user can transact using any registered identifier without creating duplicate records. |
| G2 | Users can hold financial balances in one or more wallets and transact (send, receive, pay) without overdraft — regardless of whether they access via USSD or mobile app. | Zero overdraft incidents attributable to platform logic. |
| G3 | The platform correctly applies configured limits, thresholds, and pricing rules to every transaction before any value moves. | All transactions blocked by limit or pricing rules are rejected with a clear reason before ledger write. |
| G4 | The ledger records every movement of value as an immutable, append-only entry with full traceability from transaction initiation to settlement or reversal. | Every ledger entry is queryable with its originating transaction, status, and actor. |
| G5 | External transactions (from bank, mobile money, or partner systems) can be consumed via an event stream and evaluated by the rules engine without requiring a platform-initiated transaction. | External events trigger rule evaluation and reward issuance without any manual intervention. |
| G6 | The rules engine evaluates configured milestone rules against transaction activity across both internal and external sources, issuing rewards when thresholds are met. | Reward issuance matches the configured rule conditions with zero over- or under-crediting. |
| G7 | Users can redeem points by converting them to cash through a configured redemption provider — with full ledger traceability and reconciliation support for pending or failed redemptions. | Every redemption attempt has an auditable ledger trail from initiation to completion or reversal. |
| G8 | The platform supports two deployment modes — a full wallet (financial ledger + rules engine) and a rewards-only mode (rules engine + points ledger, no financial ledger) — through tenant configuration, not separate codebases. | A tenant can be configured as rewards-only with no financial ledger modules active. |
| G9 | Administrators can configure tenants, users, merchants, roles, limits, pricing, and rules through a management interface without requiring a code deployment. | All configuration changes take effect within the same business day without a release. |

---

## 5. Non-Goals

- **Real-time FX conversion.** The platform does not perform live currency conversion. Multi-currency support within a single wallet is out of scope for Phase 1 (each currency is a separate account; money is never summed across currencies).
- **Card issuance and open-loop payment rails.** Mastercard or Visa card issuance, physical or virtual, is not in scope for Phase 1. The platform is closed-loop in Phase 1.
- **Banking licence or e-money licence functions.** The platform does not act as a regulated financial institution. Sponsor bank relationships, regulatory capital management, and prudential reporting are out of scope.
- **Automated payment file generation or bank transfer initiation.** The platform does not generate payment files or initiate transfers to external bank accounts on behalf of users. Settlement instructions are informational only in Phase 1.
- **Fraud detection and AML screening.** Rule-based fraud detection and AML transaction monitoring are out of scope. The limits and thresholds module provides velocity controls only.
- **Merchant-initiated recurring billing.** Subscriptions, standing orders, or merchant-side recurring debit instructions are out of scope.
- **~~Admin UI for rule configuration.~~ DELIVERED.** Rule/campaign authoring now ships as the admin "Campaigns" UI (all seven rule types are configurable without a code deployment). The original Phase-1 deferral no longer holds.
- **Customer support tooling.** Case management, dispute resolution workflows, and agent-facing support interfaces are out of scope.
- **Cross-border remittance origination.** The platform holds and moves value but does not originate cross-border remittance transfers. Integration with Sasai Remit for inbound remittance receipt is a future dependency.
- **Points expiry and promotional campaign management.** Promotional campaign authoring has **shipped** (campaign/time-boxed rules). **Points expiry specifically remains deferred** — time-limited points balances and points-expiry rules are out of scope for Phase 1.

---

## 6. Actors

| Actor | Description |
|---|---|
| User | A registered individual who holds a wallet or points account, initiates transactions, and redeems rewards. Self-registers phone-first (OTP + PIN). |
| Agent / Super-agent | A user type that funds customer wallets (cash-in) and receives cash-out, earning commission. Super-agents parent agents. |
| Merchant / Head-merchant | A user type that collects customer funds into a collection account (e.g. airtime) and may fund consumers via the partner API. Head-merchants parent merchants. |
| Administrator | A platform operator with authority to configure tenants, users, merchants, roles, limits, pricing rules, and reward rules. Sub-roles: **platform-admin** (full), **config-approver** (pricing/limit/tax/commission/step-up config), **user-approver** (user create/edit), **treasury-approver** (money operations), plus finance-read for analytics/reconciliation. |
| System | Automated processes that consume events, evaluate rules, execute reconciliation sweeps, drain the reward outbox, and issue notifications without human involvement. |
| Redemption provider | An external partner system that receives redemption requests and converts points to cash value; authenticates callbacks by HMAC. |
| External event source | An external system (bank, mobile money provider, partner) that emits transaction events consumed by the platform's event normaliser; every event carries HMAC proof of origin. |
| External partner (API key) | A partner integrating the money API with an API key and HMAC signature; can create users and fund/withdraw wallets, and (merchant keys) fund consumers. |

---

## 7. Functional Requirements

---

### Module 1 — Identity & User Management

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0010 | User registration via phone number | When a user registers with a phone number that is not already associated with a `user_id`, the system creates a new user record and assigns a canonical `user_id`. | P0 |
| Pay-PRD-0020 | OTP verification at registration | During mobile app registration, the system sends a one-time password to the user's registered phone number. Registration is not completed until the OTP is successfully verified. | P0 |
| Pay-PRD-0030 | PIN setup after OTP verification | After successful OTP verification, the user must set a 4–6 digit PIN before any transaction can be initiated. The PIN is stored as a hashed value. The plain PIN is never stored or logged. | P0 |
| Pay-PRD-0040 | USSD authentication via phone number and PIN | On USSD, a user is authenticated by entering their registered phone number and PIN. The session is not established until both are verified. | P0 |
| Pay-PRD-0050 | Multi-identifier registration | A user may register additional identifiers — email address, internal account number, and bank card number — against their existing `user_id`. Each identifier must be unique across the platform. | P1 |
| Pay-PRD-0060 | Identity resolution from any registered identifier | When a transaction request presents any registered identifier (phone number, email, account number, or bank card number), the system resolves it to the canonical `user_id` before processing. If no match is found, the transaction is rejected with an explicit "user not found" reason. | P0 |
| Pay-PRD-0070 | Duplicate identifier prevention | The system must reject registration of an identifier that is already associated with a different `user_id`. The error must specify which identifier is already in use. | P0 |
| Pay-PRD-0080 | User profile management | An Administrator must be able to view and update a user's profile, including name, phone number, email, and account status (active, suspended, closed). | P1 |
| Pay-PRD-0090 | Merchant registration | An Administrator must be able to register a merchant with a name, category, and associated wallet. A merchant is assigned a canonical `merchant_id` on creation. | P1 |
| Pay-PRD-0100 | Keycloak integration for platform authentication | All operator and administrator access to platform management functions is authenticated via Keycloak. User-facing PIN and OTP authentication is managed by the platform identity module, not Keycloak. | P0 |
| Pay-PRD-0101 | Phone-first self-registration with referral code | A user must be able to self-register from the mobile app without an Administrator. The flow is phone-first: an OTP is verified to issue a registration token, and setting the initial PIN completes signup. An optional referral code may be entered at signup; it is validated before OTP quota is consumed (unknown code or self-referral is rejected), and a pending referral attribution is recorded only for a self-registration that supplied a valid code. | P0 |
| Pay-PRD-0102 | User types and hierarchy | Every user has one of five types — consumer, agent, super_agent, merchant, head_merchant. Agents parent to a super-agent and merchants to a head-merchant within the same tenant; an invalid parent pairing is rejected. An Administrator may change a user's type with a mandatory reason (audited); leaving the merchant type is blocked while the user's collection balance is non-zero, and entering the merchant type requires a merchant profile. | P0 |
| Pay-PRD-0103 | Administrator user create/edit under four-eyes maker-checker | Administrator creation and editing of a user are proposals that apply only after approval by a distinct user-approver (the maker cannot approve their own request). A create proposal is rejected at proposal time if any identifier is already owned by a live user or claimed by another pending create proposal. An edit proposes only the changed fields, identifiers are read-only in edit, and a second edit is blocked while one is open for that user. Every action is audited. | P0 |
| Pay-PRD-0104 | Access-level control enforced per user status | An Administrator must be able to set a user's access level — login-lock, transaction-lock, or active. A login-lock blocks authentication; a transaction-lock blocks all money paths for that user. Enforcement reflects the user's stored status on every money path (it is not cosmetic); a blocked user is rejected before any ledger write. | P0 |
| Pay-PRD-0105 | Auth lockout, admin unlock and PIN reset | After a configurable number of consecutive failed PIN/OTP attempts the account is locked; a suspended or locked account is rejected before credentials are checked. An Administrator must be able to release a lockout without changing the PIN, and to reset a user's PIN. All remediation actions are audited. | P0 |
| Pay-PRD-0106 | Post-registration identifier linking and verification | An Administrator (or partner API) must be able to link additional identifiers — phone, email, or account number — to an existing user after registration; a card number cannot be added on this path. A newly linked account number lands unverified and can be manually verified by a platform-admin. Uniqueness is enforced (a clash is rejected) and every link/verify action is audited. | P1 |

---

### Module 2 — Account & Wallet Management

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0110 | Multiple accounts per user | A single user may hold more than one account — for example, a mobile wallet account and a points account. Each account is independently identified and holds its own balance. | P0 |
| Pay-PRD-0120 | Account types | The platform must support at least three account types: financial wallet (holds monetary balance), points account (holds reward points balance), and provider redemption wallet (holds points in transit to a redemption partner). | P0 |
| Pay-PRD-0130 | Available balance calculation | A user's available balance for any account is the total of all completed ledger credits minus the total of all completed ledger debits, minus any reserved balance. The available balance is the figure presented to the user and used for transaction eligibility checks. | P0 |
| Pay-PRD-0140 | Balance display to user | A user must be able to view their available balance for each account they hold. The balance displayed must reflect the current available balance at the time of the request. | P0 |
| Pay-PRD-0150 | Account suspension | An Administrator must be able to suspend an account. A suspended account cannot initiate or receive transactions. The reason for suspension must be recorded. | P1 |
| Pay-PRD-0160 | Tenant-scoped account creation | Account creation is scoped to a tenant. A user registered in Tenant A does not automatically have accounts in Tenant B. Cross-tenant identity resolution is out of scope for Phase 1. | P0 |
| Pay-PRD-0161 | Full account-type set | Beyond the three baseline types, the platform must support the operator and merchant account roles the ledger requires: the operator cash float, system fee-collection, commission, and tax-collection accounts, the points-issuance master, an operator bank-mirror adjustment account, and a merchant collection (e.g. airtime holding) account. Each account carries a valid type; an invalid type is rejected. | P0 |
| Pay-PRD-0162 | Per-currency wallets | A user holds a separate financial wallet per currency they transact in. Balances are held and presented per currency and are never summed or converted across currencies anywhere in the platform. | P0 |
| Pay-PRD-0163 | Automatic account provisioning | The accounts a user needs are provisioned on demand: a financial wallet for each held currency, and a points account auto-provisioned on the user's first points reward. Provisioning is race-safe and never creates duplicate accounts for the same (user, type, currency). | P0 |
| Pay-PRD-0164 | Maximum-balance ceiling per wallet | A user financial wallet may carry a configurable maximum balance. A credit that would take the wallet above its ceiling is rejected at the ledger (see Pay-PRD-0242). The ceiling applies to user financial wallets only. | P1 |

---

### Module 3 — Ledger

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0170 | Append-only ledger entries | Every transaction produces one or more immutable ledger entries. Ledger entries are never updated or deleted. A transaction reversal is recorded as a new entry, not a modification of the original. | P0 |
| Pay-PRD-0180 | Double-entry recording | Every movement of value produces at least one debit entry and one credit entry. The sum of all debit entries and credit entries across the platform must balance to zero at all times. | P0 |
| Pay-PRD-0190 | Transaction statuses | Every transaction must have a status from the following set: PENDING, COMPLETED, FAILED, REVERSED. Status transitions are: PENDING → COMPLETED, PENDING → FAILED, PENDING → REVERSED. A COMPLETED or FAILED transaction cannot be modified. | P0 |
| Pay-PRD-0200 | Idempotency on transaction submission | Every transaction request from any channel must carry a unique idempotency key. If a request is resubmitted with the same key, the system returns the result of the original transaction without processing it again. No duplicate ledger entries are created. | P0 |
| Pay-PRD-0210 | Fund reservation before external calls | When a transaction requires an external call (e.g. to a bank API or mobile money provider), the required amount must be reserved from the user's available balance before the external call is made. The reservation is released on completion or reversal. | P0 |
| Pay-PRD-0220 | Overdraft prevention | A transaction that would result in a negative available balance must be rejected before any ledger entry is created. The rejection reason must state insufficient funds. | P0 |
| Pay-PRD-0230 | Ledger entry queryability | Every ledger entry must be queryable by account, transaction ID, status, and date range. The query must return the entry amount, direction (debit or credit), status, and the idempotency key of the originating transaction. | P1 |
| Pay-PRD-0240 | Transaction history for user | A user must be able to view a list of their transactions including amount, direction, counterparty, status, and timestamp, ordered by most recent first. | P0 |
| Pay-PRD-0241 | Single posting choke point | Every movement of value across the platform — P2P, cash-in, cash-out, airtime, change-PIN fee, redemption, treasury funding/withdrawal/adjustment, partner funding, and reward issuance — must be posted through one balanced double-entry posting service. No service may hand-roll a balance read followed by a credit or debit outside this choke point. | P0 |
| Pay-PRD-0242 | Maximum-balance ceiling enforced on credit | Under the same row lock used for overdraft, a net credit that would take a user financial wallet above its configured maximum balance must be rejected before the entry is committed. When the credit was driven by a different user (e.g. an incoming P2P), the rejection returned to that user must not disclose the recipient's balance. The ceiling applies to user financial wallets only. | P0 |
| Pay-PRD-0243 | Operator cash-float non-negative floor | The operator cash float has a non-negative floor: it must be pre-funded from the bank before it can fund users, and any float-sourced funding that would drive it below zero is rejected with a distinct "insufficient float" reason. The float has no maximum-balance ceiling, so a top-up credit is never blocked. | P0 |
| Pay-PRD-0244 | Reversal and earned-payout cap exemption | Credits that restore or earn value — reversals/refunds and earned payouts such as agent commission — are exempt from the maximum-balance ceiling and must never be blocked by it. Overdraft checks on any debit legs still apply. | P0 |
| Pay-PRD-0245 | Concurrency-safe balance guard | Before any balance is read, every guarded account leg is locked for update in a canonical order (deadlock-free for multi-wallet transactions). Two concurrent full-balance debits on the same account must result in exactly one success and one rejection. | P0 |

---

### Module 4 — Payment Orchestration

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0250 | P2P transfer — user to user | A user must be able to transfer funds to another user identified by any registered identifier. The system resolves the recipient identifier to a `user_id` before processing. If the recipient is not found, the transaction is rejected before any fund movement. | P0 |
| Pay-PRD-0260 | Transaction orchestration sequence | For every payment transaction, the platform must evaluate in the following sequence before writing any ledger entry: (1) role and permission check, (2) limits and thresholds check, (3) pricing calculation. If any check fails, the transaction is rejected and the reason is returned to the user. | P0 |
| Pay-PRD-0270 | External payment execution outside DB transaction | When a payment requires an external call, the call must be made after the ledger reservation is committed and the database transaction is closed. The external call must not be executed inside a database transaction. | P0 |
| Pay-PRD-0280 | External payment success handling | When an external payment call returns a success response, the platform must update the transaction status to COMPLETED and release the reservation. | P0 |
| Pay-PRD-0290 | External payment failure handling | When an external payment call returns a failure response, the platform must update the transaction status to FAILED, reverse the ledger entries, and release the reservation. The user's available balance is fully restored. | P0 |
| Pay-PRD-0300 | External payment timeout handling | When an external payment call does not return a response within the configured timeout, the transaction must remain in PENDING status. The reconciliation job is responsible for resolving PENDING transactions. | P0 |
| Pay-PRD-0310 | Bill payment | A user must be able to initiate a bill payment to a registered merchant. The payment follows the same orchestration sequence as a P2P transfer. | P1 |
| Pay-PRD-0320 | Wallet top-up | A user must be able to top up their wallet from an external source (e.g. mobile money or bank transfer). A top-up is recorded as a credit ledger entry. | P1 |
| Pay-PRD-0321 | Agent cash-in | An agent must be able to fund a customer's wallet from the agent's own e-float. The transaction resolves the customer, assembles fee, commission, and tax into balanced legs, and credits the customer; the customer is the reward beneficiary. It is idempotent (idempotency key required). | P0 |
| Pay-PRD-0322 | Cash-out to an agent | A subscriber must be able to withdraw value to an agent. The recipient must be an agent — a non-agent recipient is rejected. The transaction assembles charges and posts through the choke point; it is idempotent. | P0 |
| Pay-PRD-0323 | Airtime recharge with asynchronous provider settlement | A user must be able to recharge airtime through a merchant/provider. Funds are reserved as PENDING, the provider is dispatched only after commit, and a signed provider callback or an Administrator resolution transitions the recharge to COMPLETED on a successful vend or appends a REVERSED reversal on failure. A reward fires only on successful-vend completion, never on the reservation. It is idempotent. | P0 |
| Pay-PRD-0324 | Charged change-PIN | Changing a PIN is an idempotent money path that may carry a configured fee. The current PIN is verified, a new PIN equal to the current one is rejected, any fee is posted through the choke point, and the PIN is re-hashed. The action is audited. | P1 |
| Pay-PRD-0325 | Operator treasury movements under N-eyes maker-checker | Operators must be able to fund and withdraw user wallets, adjust system wallets (including topping up the cash float from the bank), and manage bank-mirror accounts. Each is a proposal applied only once N distinct approvers (treasury-approver; maker excluded) have approved; apply is idempotent so re-approval cannot double-post. Every action is audited. | P0 |
| Pay-PRD-0326 | External partner money API | A partner authenticated by API key and HMAC signature must be able to create users and fund or withdraw user wallets, and (with a merchant-bound key) fund a consumer from the merchant's own wallet. The tenant is always derived from the key (never the request body), the partner cannot set privileged fields, requests are idempotent and per-key rate-limited, and an empty cash float is masked to a generic "funding temporarily unavailable" response rather than leaking float state. | P1 |
| Pay-PRD-0327 | Step-up PIN re-authentication | For a transaction whose amount exceeds a configured step-up threshold, the user must re-enter their PIN before it proceeds. The control is fail-closed: with no policy configured a PIN is required; a missing PIN returns a step-up-required response and a wrong PIN is rejected. Both rejections occur before any ledger write, so the request may be safely replayed with the same idempotency key. | P0 |

---

### Module 5 — Limits & Thresholds

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0330 | Per-transaction minimum amount | An Administrator must be able to configure a minimum transaction amount per account type and transaction type. Transactions below the minimum are rejected before any ledger entry is created. | P0 |
| Pay-PRD-0340 | Per-transaction maximum amount | An Administrator must be able to configure a maximum transaction amount per account type and transaction type. Transactions above the maximum are rejected before any ledger entry is created. | P0 |
| Pay-PRD-0350 | Daily transaction count limit | An Administrator must be able to configure a maximum number of transactions of a given type that a user may initiate within a calendar day. When the limit is reached, further transactions of that type are rejected until the next calendar day. | P0 |
| Pay-PRD-0360 | Daily value limit | An Administrator must be able to configure a maximum total value of transactions of a given type that a user may initiate within a calendar day. When the limit is reached, further transactions are rejected until the next calendar day. | P0 |
| Pay-PRD-0370 | Limits applied before ledger write | All limit and threshold checks must be evaluated and either pass or fail before any ledger entry is created. A limit breach must produce a rejection reason clearly stating which limit was exceeded. | P0 |
| Pay-PRD-0380 | Limits configurable per tenant | Limit values are tenant-scoped. Different tenants may have different limit configurations for the same transaction type. | P1 |
| Pay-PRD-0381 | Rolling weekly and monthly count and value limits | Beyond daily limits, an Administrator must be able to configure rolling weekly and monthly count and value caps per transaction type. A transaction that would breach any window cap is rejected with the specific window and axis named. | P1 |
| Pay-PRD-0382 | Cumulative wallet send and receive limits | An Administrator must be able to configure cumulative send and receive caps on a wallet across all services (per window). A send that would breach the wallet send cap, or a receipt that would breach the recipient's receive cap, is rejected before any ledger write. | P1 |
| Pay-PRD-0383 | Per-wallet maximum-balance limit | An Administrator must be able to configure a maximum-balance limit per currency wallet. This value is the ceiling resolved by the ledger guard (Pay-PRD-0242). | P1 |
| Pay-PRD-0384 | Type-aware limits | Limit configurations may be scoped by user type. When resolving a user's limit, an exact user-type match takes precedence over a type-agnostic default; there are no per-user overrides. | P1 |
| Pay-PRD-0385 | Reward-issuance budgets | An Administrator must be able to cap reward issuance per scope (tenant and/or rule) and window (e.g. rolling 24h/7d, calendar month, lifetime). The budget is checked before any reward credit; an issuance that would breach it is rejected. | P1 |

---

### Module 6 — Pricing Engine

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0390 | Fee configuration per transaction type | An Administrator must be able to configure a fee for each transaction type. A fee may have a fixed component (flat amount), a variable component (percentage of transaction value), or both. Either component may be zero. | P0 |
| Pay-PRD-0400 | Fee calculation before ledger write | The fee applicable to a transaction must be calculated before any ledger entry is created. The fee amount must be included in the total debit applied to the user's account. | P0 |
| Pay-PRD-0410 | Fee displayed to user before confirmation | On all channels, the calculated fee must be presented to the user before they confirm the transaction. The user must confirm with the fee visible. | P0 |
| Pay-PRD-0420 | Zero-fee transactions | Transactions with a configured fee of zero must be processed without applying any fee. The pricing check must still execute and confirm zero fee before proceeding. | P1 |
| Pay-PRD-0430 | Pricing configurable per tenant | Fee configurations are tenant-scoped. Different tenants may apply different fees to the same transaction type. | P1 |
| Pay-PRD-0431 | Amount-band (slab) fees | A fee configuration may resolve by amount band, so that different transaction-value ranges attract different fixed and percentage components (with an optional cap on the percentage). The applicable band is resolved before charge assembly. | P1 |
| Pay-PRD-0432 | Fee-inclusive vs fee-exclusive treatment | A fee (and, where applicable, commission and tax) may be charged on top of the amount (exclusive) or absorbed within it (inclusive). The chosen treatment is assembled into balanced ledger legs correctly for each combination. | P1 |
| Pay-PRD-0433 | Agent commission configuration | An Administrator must be able to configure agent commission per transaction type, currency, and user type, with optional amount bands. Commission is posted as a payout leg in the transaction's charge assembly. | P1 |
| Pay-PRD-0434 | Tax overlay on fee and commission | An Administrator must be able to configure independent tax rates applied to the fee and to the commission per tenant and currency. Taxes are assembled as their own balanced legs. | P1 |
| Pay-PRD-0435 | Type-aware pricing | Fee configurations may be scoped by user type. When resolving a user's fee, an exact user-type match takes precedence over a type-agnostic default. | P1 |
| Pay-PRD-0436 | Fail-closed service gating | A money service may execute only if BOTH a pricing configuration AND a limit configuration resolve for the acting user's type and scope; if either is absent the request is rejected before any ledger write. This is unconditional — never gated by a per-tenant flag or environment. A zero fee or an unlimited limit must be an explicitly configured row; silent zero-fee or limitless pass-through is forbidden. | P0 |
| Pay-PRD-0437 | Configuration governance via four-eyes maker-checker | Changes to pricing, limit, tax, commission, and step-up configuration are proposed by a maker and applied only after approval by a distinct config-approver. At most one open request may exist per configuration scope; a revised proposal re-validates tenant and scope exactly as the original; multi-band payloads are validated as a set and applied all-or-none. Every action is audited. | P0 |

---

### Module 7 — Roles & Permissions

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0440 | Role assignment to users | An Administrator must be able to assign one or more roles to a user. A user with no assigned role may not initiate transactions. | P0 |
| Pay-PRD-0450 | Transaction permission by role | Each role must have a defined set of permitted transaction types. A transaction type not permitted for a user's role is rejected at the role check step with a "not authorised" reason. | P0 |
| Pay-PRD-0460 | Role check before limit and pricing checks | The role and permission check must be evaluated first in the transaction orchestration sequence. A role check failure must reject the transaction immediately without evaluating limits or pricing. | P0 |
| Pay-PRD-0470 | Role configuration by Administrator | An Administrator must be able to create, update, and deactivate roles, and assign or remove transaction permissions per role, without a code deployment. | P1 |
| Pay-PRD-0471 | Administrator governance sub-roles | Administrator authority is partitioned into governance sub-roles — platform-admin, config-approver, user-approver, and treasury-approver. Each maker-checker approval requires an approver holding the matching role, a maker may never approve their own request, and N-eyes approvals require distinct approvers. Platform-admin may act across domains. | P0 |

---

### Module 8 — Event Ingestion & Normalisation

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0480 | Internal event emission after transaction completion | When any internal transaction reaches COMPLETED or FAILED status, the platform must emit a transaction event containing at minimum: `event_id`, `user_id`, `transaction_type`, `amount`, `currency`, `merchant_id` (if applicable), and `timestamp`. | P0 |
| Pay-PRD-0490 | External event consumption | The platform must consume transaction events from an external event stream. Each consumed event must be normalised into the standard transaction event schema before being passed to the rules engine. | P0 |
| Pay-PRD-0495 | External event source authentication and integrity | Every external event source must be registered on the platform before its events are accepted. Events from unregistered sources must be rejected and logged. Each event from a registered source must carry a verifiable proof of origin. Events that fail origin verification must be discarded without triggering rule evaluation, and the failure must be recorded in the security audit log with the source identifier, timestamp, and rejection reason. | P0 |
| Pay-PRD-0500 | Event deduplication | Before passing any event (internal or external) to the rules engine, the platform must check the `event_id` against a log of previously processed events. A duplicate event must be discarded without triggering rule evaluation. | P0 |
| Pay-PRD-0510 | External event schema mapping | For each configured external event source, an Administrator must be able to define the field mapping from the external event schema to the standard transaction event schema. | P1 |
| Pay-PRD-0520 | Failed event handling | If an external event cannot be normalised due to a missing required field or unrecognised format, the event must be logged as failed with the reason. Failed events must not trigger rule evaluation and must not affect the state of any user account. | P0 |
| Pay-PRD-0521 | Deployment-mode gating of rewards | The tenant deployment mode is load-bearing for rewards. External events are accepted for reward evaluation only for `rewards`-mode tenants; a `wallet`-mode tenant issues no rewards at all; a `both`-mode tenant drives rewards from internal wallet activity via a transactional outbox rather than external events. An event arriving in the wrong mode is rejected and audited. | P0 |
| Pay-PRD-0522 | Per-user event ordering | Events are partitioned by `user_id` so that a given user's events are processed in order, preserving the correctness of count- and streak-based progress. | P1 |

*Note: Pay-PRD-0480 internal event emission is realised for the reward pipeline via the transactional outbox (see Pay-PRD-0521); a general-purpose internal transaction-event stream for other consumers is not otherwise built.*

---

### Module 9 — Rules Engine

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0530 | Rule definition — transaction type | A rule must be bound to a specific transaction type (e.g. P2P, bill payment, top-up). Only events of the bound transaction type qualify for rule evaluation. | P0 |
| Pay-PRD-0540 | Rule definition — count threshold | A rule must specify a transaction count threshold. The rule fires when the user's qualifying transaction count for the current cycle reaches the threshold. | P0 |
| Pay-PRD-0550 | Rule definition — time window | A rule must specify a time window (lifetime, calendar month, or rolling 7 days) within which qualifying transactions are counted. Transactions outside the window do not contribute to the count. | P0 |
| Pay-PRD-0560 | Rule definition — reward | A rule must specify the reward to be issued on firing: reward type (points or cashback) and value. | P0 |
| Pay-PRD-0570 | Milestone rule — counter reset after trigger | When a milestone rule fires, the user's qualifying transaction counter for that rule is reset to zero. The next cycle begins immediately. The same threshold must be reached again for the rule to fire a second time. | P0 |
| Pay-PRD-0580 | Configurable recurrence | A rule must support a stop-after-n-triggers configuration. When set to a positive integer, the rule is deactivated for the user after it has fired that many times. When null, the rule fires indefinitely with counter reset after each trigger. | P0 |
| Pay-PRD-0590 | User rule progress tracking | For each user and each active rule, the platform must maintain a record of the current qualifying transaction count, the total number of times the rule has fired for the user, the timestamp of the last trigger, and the start of the current window. | P0 |
| Pay-PRD-0600 | Rules engine source-agnostic | The rules engine must evaluate rules identically regardless of whether the triggering event originated from an internal transaction or an external event source. The source is not a factor in rule evaluation. | P0 |
| Pay-PRD-0610 | Rule evaluation does not block transaction | For internal transactions, rule evaluation must occur after the transaction reaches COMPLETED status. A rule evaluation failure must not reverse or delay the originating transaction. | P0 |
| Pay-PRD-0615 | Streak rule type | A rule may be configured as a streak rule. A streak rule requires a user to complete a qualifying transaction on each consecutive unit within a defined window (e.g. one P2P per week for 4 consecutive weeks). The streak fires a reward when the full consecutive sequence is completed. If the user misses a unit, the streak counter resets to zero and the sequence must begin again. | P1 |
| Pay-PRD-0616 | Streak break event emission | When a user's streak is broken, the platform must emit a streak-broken event containing the user ID, rule ID, the streak length at the point of breaking, and the timestamp. This event is available for consumption by external engagement tools. | P1 |
| Pay-PRD-0617 | First-time event rule type | A rule may be configured as a first-time rule. A first-time rule fires exactly once per user — the first time the qualifying event occurs. Subsequent occurrences of the same event type do not trigger evaluation for that rule. | P0 |
| Pay-PRD-0618 | Value-based rule condition | A rule may specify a minimum transaction amount as an additional condition. Only events whose transaction value meets or exceeds the minimum qualify for that rule. Count-based and streak conditions are evaluated only against qualifying-value events. | P1 |
| Pay-PRD-0619 | Composite rule — multiple conditions | A rule may specify more than one transaction type condition joined by an AND or OR operator. For AND rules, all conditions must be satisfied within the defined time window before the rule fires. For OR rules, any single condition being met fires the rule. Each condition tracks its own progress independently. | P2 |
| Pay-PRD-0621 | Campaign rule — active date range | A rule may be configured with a start date and an end date. A campaign rule is only evaluated for events that occur within the active date range. Events outside the range do not contribute to progress. When the end date passes, the rule is automatically deactivated. | P1 |
| Pay-PRD-0622 | Referral rule | A rule may be configured as a referral rule. A referral rule fires a reward for the referring user when a referred user completes a defined qualifying action (e.g. first top-up, first P2P). The referring user is identified by a referral code linked to their user ID. The reward fires on the referred user's qualifying event, not on the act of sharing the code. Both the referring user and the referred user may receive separate rewards, configured independently. | P1 |
| Pay-PRD-0623 | Bonus multiplier — time-limited points boost | An Administrator must be able to configure a multiplier period during which points earned from qualifying rules are multiplied by a configured factor (e.g. 2x, 3x). The multiplier applies to the points value of any reward issued during the active period. The multiplier period has a start date, an end date, and an optional scope (all rules or specific rule IDs). | P1 |
| Pay-PRD-0624 | Rule audience — segment binding | A rule may be bound to a named audience segment. When a segment is configured, only users who are members of that segment at the time of event evaluation are eligible for progress tracking and reward issuance. Users outside the segment are skipped silently — no progress is recorded and no rejection is logged. | P1 |

*Note: all seven rule types are built. The signup-triggered referral reward (Pay-PRD-0622) fires on completed self-registration. Two evaluation paths are logic-complete and unit-tested but **not yet wired to the live internal-transaction pipeline**: the composite rule's counting of internal `transactions` (Pay-PRD-0619) and the referral rule's Nth-transaction trigger (Pay-PRD-0622). Rewards from the external-event and internal-outbox paths are unaffected.*

---

### Module 10 — Reward Issuance

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0620 | Points reward — credit to points account | When a rule fires and the reward type is points, the system must credit the configured point value to the user's points account as a ledger entry. The ledger entry must reference the rule ID and the triggering event ID. | P0 |
| Pay-PRD-0630 | Cashback reward — credit to financial wallet | When a rule fires and the reward type is cashback, the system must credit the configured cashback value to the user's financial wallet as a ledger entry. The ledger entry must reference the rule ID and the triggering event ID. | P0 |
| Pay-PRD-0640 | Reward issuance notification | When a reward is issued, the user must receive a notification stating the reward type, the value credited, and the rule that triggered it. | P1 |
| Pay-PRD-0650 | Reward issuance in rewards-only deployment mode | In rewards-only mode (no financial ledger), all rewards must be issued as points credits to the user's points account. Cashback reward types are not available in rewards-only mode. | P0 |
| Pay-PRD-0651 | Reward issuance idempotency | A qualifying firing issues a reward at most once, enforced structurally by uniqueness over (user, rule, triggering event). A retried issuance refetches the existing reward event and does not create a second credit. | P0 |
| Pay-PRD-0652 | Points account auto-provisioning | If a user has no points account when their first points reward is issued, one is provisioned race-safely as part of issuance, without an Administrator action. | P0 |
| Pay-PRD-0653 | Mode-aware, loop-safe issuance | Rewards are issued only where the tenant deployment mode enables them. Reward-issuance transaction types are themselves excluded from being rewardable, so issuing a reward can never re-trigger reward evaluation. All reward movements post through the ledger choke point (Pay-PRD-0241). | P0 |

---

### Module 11 — Redemption

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0660 | Redemption request initiation | A user must be able to initiate a redemption of their points balance. The user specifies the amount of points to redeem and the redemption provider. | P0 |
| Pay-PRD-0670 | Atomic two-legged ledger entry on initiation | On redemption initiation, the platform must atomically create two PENDING ledger entries in a single database transaction: a debit from the user's points account and a credit to the provider redemption wallet. If either entry cannot be created, both are rolled back. | P0 |
| Pay-PRD-0680 | External provider call after ledger commit | The call to the redemption provider's external API must be made after the two-legged ledger entries are committed and the database transaction is closed. The external call must not be made inside a database transaction. | P0 |
| Pay-PRD-0690 | Redemption success handling | When the redemption provider confirms success, both ledger entries must be updated to COMPLETED status. The user is notified of the successful redemption. | P0 |
| Pay-PRD-0700 | Redemption failure handling | When the redemption provider returns a failure response, both ledger entries must be reversed. The user's points balance is fully restored. The user is notified of the failure with the reason. | P0 |
| Pay-PRD-0710 | Redemption timeout and PENDING state | When the redemption provider does not respond within the configured timeout, both ledger entries remain in PENDING status. The reconciliation job is responsible for resolving PENDING redemptions. | P0 |
| Pay-PRD-0720 | Redemption status check | The platform must be able to query the redemption provider's status check endpoint for any PENDING redemption. The result of the status check must be used to update the redemption to COMPLETED or initiate a reversal. | P0 |
| Pay-PRD-0730 | Redemption retry configuration | An Administrator must be able to configure: maximum number of status check retries, interval between retries (in minutes), and the threshold after which a PENDING redemption is escalated to MANUAL_REVIEW. | P1 |
| Pay-PRD-0740 | Redemption overdraft prevention | A redemption request for an amount greater than the user's available points balance must be rejected before any ledger entry is created. | P0 |

*Note: Pay-PRD-0720 provider status-check polling (real outbound HTTP to a provider status endpoint with auto-confirm/fail) is not yet built; PENDING redemptions are today resolved through the reconciliation sweep and manual review (Module 12) and signed provider callbacks.*

---

### Module 12 — Reconciliation

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0750 | Automated PENDING sweep | The platform must run an automated reconciliation job on a configurable schedule that identifies all PENDING transactions older than a configured threshold. | P0 |
| Pay-PRD-0760 | Status check on PENDING transactions | For each PENDING transaction identified by the sweep, the platform must call the relevant external system's status check endpoint to determine the outcome. | P0 |
| Pay-PRD-0770 | COMPLETED resolution | When the external system confirms a PENDING transaction as successful, the platform must update the transaction to COMPLETED and release any reservation. | P0 |
| Pay-PRD-0780 | REVERSED resolution | When the external system confirms a PENDING transaction as failed, the platform must reverse the ledger entries, update the transaction to REVERSED, release the reservation, and restore the user's available balance. | P0 |
| Pay-PRD-0790 | Escalation to MANUAL_REVIEW | When a PENDING transaction has been retried the maximum configured number of times without a conclusive response, the transaction must be escalated to MANUAL_REVIEW status and flagged for operator attention. A transaction in MANUAL_REVIEW is excluded from further automated retry. | P1 |
| Pay-PRD-0800 | Reconciliation audit log | Every action taken by the reconciliation job — sweep execution, status check call, status update, escalation — must be recorded in an audit log with timestamp, transaction ID, and outcome. | P1 |

---

### Module 13 — Notifications

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0810 | Transaction completion notification | When a transaction reaches COMPLETED status, the user who initiated it must receive a notification confirming the transaction, the amount, the counterparty, and the resulting available balance. | P0 |
| Pay-PRD-0820 | Transaction failure notification | When a transaction reaches FAILED or REVERSED status, the initiating user must receive a notification stating that the transaction was unsuccessful and the reason. | P0 |
| Pay-PRD-0830 | Reward notification | When a reward is issued, the user must receive a notification stating the reward type, the value, and the triggering rule. | P1 |
| Pay-PRD-0840 | Notification channel | Notifications must be delivered via SMS for USSD users and via push notification for mobile app users. Email is a secondary channel and optional in Phase 1. | P0 |
| Pay-PRD-0850 | Notification delivery decoupled from transaction | Notification delivery must not block or delay the transaction processing pipeline. A notification delivery failure must not cause the originating transaction to fail. | P0 |

*Note: this module is **not yet implemented**. No SMS/push notification service exists. The only shipped reward-notification surface is the in-app mobile reward-celebration overlay (see Module 16, Pay-PRD-1053). These requirements remain the target for Phase 2.*

---

### Module 14 — Tenant & Platform Configuration

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0860 | Tenant creation | An Administrator must be able to create a new tenant with a name, deployment mode (wallet or rewards-only), base currency, and status (active or inactive). | P0 |
| Pay-PRD-0870 | Deployment mode: wallet | A tenant configured in wallet mode has all platform modules active: identity, accounts, financial ledger, payment orchestration, limits, pricing, roles, rules engine, points ledger, and redemption. | P0 |
| Pay-PRD-0880 | Deployment mode: rewards-only | A tenant configured in rewards-only mode has only the following modules active: event normaliser, rules engine, points ledger, reward issuance, and notifications. Financial ledger, payment orchestration, limits, and pricing modules are inactive. User authentication is not required. | P0 |
| Pay-PRD-0890 | Tenant isolation | Data, configuration, and balances belonging to one tenant must not be accessible to users or administrators of another tenant. | P0 |
| Pay-PRD-0900 | Tenant-level configuration changes without code deployment | All tenant configuration — limits, pricing, roles, notification settings, event source mappings — must be modifiable by an Administrator at runtime without requiring a platform code deployment. | P1 |
| Pay-PRD-0901 | Instrument (currency / points) catalog | An Administrator must be able to manage the catalog of instruments (currencies and points units) — list, create, update, and soft-delete — with a duplicate code rejected. Creating a new financial currency backfills existing users' wallets and provisions that currency's system accounts. | P1 |
| Pay-PRD-0902 | Service catalog with per-service access policy | An Administrator must be able to define the transaction types (services) offered, each declaring the user types permitted to use it and the channels it may be used on. The access policy is enforced on every money path; a disallowed user type or channel is rejected. | P0 |
| Pay-PRD-0903 | Tenant auto-provisioning on creation | Creating a tenant must automatically provision its baseline instruments and services in the tenant's own base currency (not a fixed default), together with the tenant's system accounts. A creation path that leaves an empty, unusable tenant is a defect. | P0 |
| Pay-PRD-0904 | Per-tenant admin-UI branding | An Administrator must be able to brand the admin interface per tenant from two brand colours and an optional icon, from which a full palette is derived. Applying branding re-themes the app for that tenant; status colours remain constant. | P2 |
| Pay-PRD-0905 | External API-key management | An Administrator must be able to mint, list, and revoke partner API keys. The secret is shown once on creation and stored encrypted at rest; a key may optionally be bound to a merchant user. | P1 |
| Pay-PRD-0906 | External event-source registration | An Administrator must be able to register an external event source with an encrypted shared secret and a field mapping. A duplicate source key is rejected. (Integrity enforcement is specified in Pay-PRD-0495.) | P0 |
| Pay-PRD-0907 | Governed configuration and unified approvals | Configuration and money/user operations are governed by maker-checker (see Pay-PRD-0437, Pay-PRD-0325, Pay-PRD-0103). A single, role-gated approvals surface aggregates the configuration, money-operation, and user-operation queues, showing each operator only the queues matching their approver roles. | P1 |
| Pay-PRD-0908 | Analytics and reporting | The platform must provide a read-only, tenant-scoped KPI dashboard covering transactions, users (including daily/weekly/monthly active), revenue, rewards, liquidity, and net flow, grouped by user type where relevant. Money is never summed or converted across currencies — every money metric is reported per currency. Revenue is the operator fee only (tax pass-through and agent commission excluded). An invalid range or granularity is rejected. | P1 |

---

### Module 15 — Audience Segmentation

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0910 | Uploaded list segment | An Administrator must be able to create a named segment by uploading a file of phone numbers or user IDs. The platform resolves each entry to a canonical user_id and stores the resolved list under the segment name. Unresolvable entries must be reported to the Administrator with a count of failures before the segment is saved. | P1 |
| Pay-PRD-0920 | Behaviour-based segment | An Administrator must be able to create a named segment by defining one or more behavioural conditions against user activity data. Supported conditions must include at minimum: last transaction date (before or after a relative or absolute date), total transaction count (less than or greater than a value), account registration date range, current tier, and current points balance. | P1 |
| Pay-PRD-0930 | Segment condition combining | When a behaviour-based segment specifies more than one condition, the Administrator must be able to configure whether the conditions are combined with AND (user must meet all) or OR (user must meet any one). | P2 |
| Pay-PRD-0940 | Segment membership evaluation at rule time | Behaviour-based segment membership is evaluated at the time each event is processed by the rules engine, not pre-computed. A user who meets the segment conditions at event time is treated as a member. A user who no longer meets the conditions is excluded without any manual update to the segment. | P1 |
| Pay-PRD-0950 | Segment naming and management | An Administrator must be able to view all defined segments, see their type (uploaded or behavioural), their condition summary, and the rules they are currently bound to. An Administrator must be able to deactivate a segment. Deactivating a segment removes audience restriction from all rules bound to it — those rules revert to platform-wide eligibility. | P1 |
| Pay-PRD-0960 | Uploaded list refresh | An Administrator must be able to replace the user list on an existing uploaded segment by uploading a new file. The replacement takes effect from the next event evaluation. The prior list is retained in history with the date it was replaced. | P2 |

*Note: static, admin-assigned segments (create, assign users, bind to rules — Pay-PRD-0910/0950/0624) are built. Behaviour-based / dynamic segments and their evaluation-time membership (Pay-PRD-0920/0930/0940/0960) are **Planned** — dynamic segments are deferred to Phase 2.*

---

### Module 16 — Rewards Catalog & User Journey

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-0970 | Points balance display | A user must be able to view their current available points balance, their total lifetime points earned, and the total points redeemed to date. | P0 |
| Pay-PRD-0980 | Points transaction history | A user must be able to view a list of all points ledger entries, showing for each entry: the points amount, whether it was a credit or debit, the event that triggered it (transaction type or rule name), and the date. Entries must be ordered most recent first. | P0 |
| Pay-PRD-0990 | Tier status display | A user must be able to view their current tier name, the points or activity threshold required to reach the next tier, and their current progress toward that threshold expressed as a value and a percentage. | P1 |
| Pay-PRD-1000 | Next milestone nudge | For each active rule for which the user has progress in the current cycle, the platform must compute and display the remaining actions required to trigger the next reward. The nudge must state the transaction type, the remaining count or streak units, and the reward value that will be issued on completion. | P1 |
| Pay-PRD-1010 | Badges and achievements display | A user must be able to view all badges they have earned, including the badge name and the date it was awarded. Badges not yet earned must be visible as locked, showing the condition required to unlock them. | P1 |
| Pay-PRD-1020 | Active challenges display | A user must be able to view all challenges they are currently eligible for, including the challenge description, the reward on completion, the deadline (if applicable), and their current progress toward completion. | P1 |
| Pay-PRD-1030 | Redemption history | A user must be able to view their full redemption history, showing for each redemption: the points redeemed, the provider, the date initiated, and the current status (PENDING, COMPLETED, FAILED, REVERSED). | P0 |
| Pay-PRD-1040 | Points expiry notice | When a user has points that are scheduled to expire within a configurable warning window (default 30 days), the rewards catalog must display a prominent notice stating the number of points expiring and the expiry date. This notice must remain visible until the points have expired or been redeemed. | P1 |
| Pay-PRD-1050 | Rewards catalog available in rewards-only mode | The rewards catalog must be available to users in both wallet and rewards-only deployment modes. In rewards-only mode, the financial wallet balance and redemption history sections are hidden. All other catalog sections remain visible. | P1 |
| Pay-PRD-1051 | Rewards catalog with per-rule progress | A user must be able to view a catalog of the active rules they are eligible for, each showing a current/target progress value and label and a status of earned, in-progress, or locked. Rules bound to a segment the user is not in are excluded from the catalog. | P0 |
| Pay-PRD-1052 | Recent earned rewards | A user must be able to view their most recent reward events, newest first, each showing the reward value in its own unit (points or the cashback currency) and an unseen indicator. | P1 |
| Pay-PRD-1053 | One-shot reward celebration | The first unseen earned reward must trigger a one-shot in-app celebration; dismissing it marks the user's own unseen rewards as seen. Marking rewards seen is idempotent and scoped to the calling user. | P1 |
| Pay-PRD-1054 | Refer-a-friend surface | When a user has a referral code, the rewards surface must display it with a share affordance so the user can invite others. The code is shown whenever one exists, independent of whether the rewards catalog is enabled for the tenant. | P1 |
| Pay-PRD-1055 | Mode-gated rewards surface | In a `wallet`-mode tenant the rewards surface is disabled and shows an empty catalog, but the user's referral code is still returned. | P1 |

*Note: tiers (Pay-PRD-0990), next-milestone nudges (Pay-PRD-1000), badges (Pay-PRD-1010), challenges (Pay-PRD-1020), and points-expiry notices (Pay-PRD-1040) are **Planned — not yet built**. The shipped user journey is the per-rule progress catalog, recent rewards, the celebration, and refer-a-friend (Pay-PRD-1051–1055) plus points balance/history and redemption history.*

---

### Module 17 — External Engagement Event Emission

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| Pay-PRD-1060 | Reward issued event | When a reward is issued to a user, the platform must emit an event containing: user ID, rule ID, rule name, reward type, reward value, and timestamp. This event is intended for consumption by external engagement tools and must not be used internally for any platform action. | P1 |
| Pay-PRD-1070 | Tier change event | When a user's tier changes — either an upgrade or a downgrade — the platform must emit an event containing: user ID, previous tier name, new tier name, and timestamp. | P1 |
| Pay-PRD-1080 | Streak broken event | When a user's streak rule progress resets due to a missed period, the platform must emit an event containing: user ID, rule ID, rule name, the streak length at the point of breaking, and the timestamp. | P1 |
| Pay-PRD-1090 | Milestone approaching event | When a user's progress on a rule reaches a configurable threshold below the trigger (e.g. one action remaining), the platform must emit an event containing: user ID, rule ID, rule name, remaining count to trigger, and the reward value on completion. The threshold at which this event fires must be configurable per rule. | P1 |
| Pay-PRD-1100 | Points expiry approaching event | When a user has points that will expire within the configured warning window, the platform must emit an event containing: user ID, points amount expiring, expiry date, and current available points balance. This event fires once per expiry batch, not daily. | P1 |
| Pay-PRD-1110 | Challenge completed event | When a user completes a challenge, the platform must emit an event containing: user ID, challenge ID, challenge name, reward issued, and timestamp. | P2 |
| Pay-PRD-1120 | Referral converted event | When a referred user completes their qualifying action and a referral reward fires, the platform must emit an event containing: referring user ID, referred user ID, rule ID, and timestamp. | P2 |

*Note: this module is **not yet implemented**. The outbound engagement topics are reserved in configuration, but no producer emits to them and there is no WebEngage (or other engagement-tool) integration. These requirements remain the target for Phase 2.*


## 8. Non-Functional Requirements

### 8.1 Response Times

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| NFR-0010 | Transaction response time — USSD | A transaction initiated via USSD must return a response to the user within 8 seconds under normal load. This covers role check, limits check, pricing, ledger write, and response to channel. | P0 |
| NFR-0020 | Transaction response time — mobile app | A transaction initiated via mobile app must return a response within 5 seconds under normal load. | P0 |
| NFR-0030 | Balance read response time | A user's available balance must be returned within 2 seconds of request on any channel. | P0 |
| NFR-0040 | Identity resolution response time | Resolution of any registered identifier (phone, email, account number, card) to a canonical `user_id` must complete within 1 second. | P0 |
| NFR-0050 | Rules engine evaluation time | Evaluation of all active rules for a user following a qualifying event must complete within 500 milliseconds. | P1 |
| NFR-0060 | Idempotent request response time | Resubmission of a request with an existing idempotency key must return the original result within the same response time SLA as the original channel. | P0 |
| NFR-0070 | Reconciliation sweep frequency | The automated reconciliation job must run at least once every 15 minutes. Each sweep must complete within 5 minutes for a batch of up to 1,000 PENDING transactions. | P1 |
| NFR-0080 | Redemption status check response time | A redemption status check query to an external provider must time out and be retried if no response is received within a configurable threshold (default 30 seconds). | P1 |

---

### 8.2 Reliability & Data Integrity

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| NFR-0090 | Platform availability | The platform must target 99.5% uptime on a rolling 30-day basis, excluding planned maintenance windows communicated at least 48 hours in advance. | P1 |
| NFR-0100 | Ledger balance accuracy | The sum of all debit and credit ledger entries across all accounts must balance to zero at all times. Any imbalance detected is treated as a critical incident. | P0 |
| NFR-0110 | No duplicate reward issuance | A qualifying event may trigger reward issuance at most once. If the reward issuance step fails and is retried, the retry must not produce a second reward credit for the same event. | P0 |
| NFR-0120 | Scalability — concurrent users | The platform must support a minimum of 500 concurrent active sessions without degradation in response time SLAs. | P1 |
| NFR-0130 | External API call isolation | The platform must not hold open database transactions while waiting for responses from external systems. All external calls must occur after database transactions are committed. | P0 |
| NFR-0140 | Configurable timeout thresholds | Timeout values for all external calls (payment rails, redemption providers, status checks) must be configurable per integration without a platform code deployment. | P1 |
| NFR-0150 | Data retention | Ledger entries, audit logs, security logs, and transaction records must be retained for a minimum of 7 years. These records must not be modifiable or deletable by any automated process. | P1 |
| NFR-0160 | Audit trail completeness | Every configuration change, transaction status change, rule trigger, reconciliation action, reward issuance, and security event must be recorded in an audit log with actor, timestamp, and before/after values where applicable. | P0 |

---

### 8.3 Security

| Req. ID | Requirement | Acceptance Criteria | Priority |
|---|---|---|---|
| NFR-0170 | Credential protection | User credentials — including PINs, OTPs, and session tokens — must never appear in plain form in logs, audit records, API responses, error messages, or database fields. Any field storing a credential must use a one-way protective transformation. | P0 |
| NFR-0180 | Session expiry | An authenticated user session on any channel must expire after a configurable period of inactivity. An expired session requires re-authentication before any transaction can be initiated. The default inactivity timeout must be no greater than 5 minutes on USSD and 15 minutes on mobile app. | P0 |
| NFR-0190 | Failed authentication lockout | After a configurable number of consecutive failed PIN or OTP attempts, the user's account must be temporarily locked. The lockout duration and attempt threshold must be configurable by an Administrator. The user must be notified of the lockout. | P0 |
| NFR-0200 | External event source registration | Only event sources that have been explicitly registered and approved by an Administrator may deliver events to the platform. Events from unregistered sources must be rejected before any processing occurs. | P0 |
| NFR-0210 | External event integrity verification | Every event received from an external source must carry a proof of origin. Events that fail integrity verification must be rejected, logged in the security audit trail, and must not trigger any platform action. | P0 |
| NFR-0220 | Tenant data isolation | No user, administrator, or process operating within one tenant may read, write, or affect data belonging to another tenant. Tenant boundaries must be enforced at every data access layer. | P0 |
| NFR-0230 | Least privilege access | Each platform actor (user, merchant, administrator, system process) must be granted only the permissions required for their defined role. Access to financial data, configuration, and audit logs must be restricted by role. | P0 |
| NFR-0240 | Sensitive data masking in logs | Transaction amounts, account identifiers, and personal identifiable information (PII) must be masked or truncated in application logs. Full values must only be accessible through authorised audit queries, not raw log files. | P1 |
| NFR-0250 | Administrator action audit trail | Every action taken by an Administrator — including configuration changes, account suspensions, manual transaction triggers, and rule changes — must be recorded with the Administrator's identity, timestamp, and the before and after state of the affected record. | P0 |
| NFR-0260 | Secure communication channels | All communication between the platform and external systems — partner APIs, redemption providers, event sources — must occur over encrypted connections. Unencrypted communication with external systems must not be permitted. | P0 |
| NFR-0270 | Fraud signal — unusual reward volume | If a single user's reward issuance volume within a 24-hour period exceeds a configurable threshold, the platform must flag the activity for Administrator review. Flagging must not automatically block the user but must create a visible alert. | P1 |
| NFR-0280 | Account takeover protection | The platform must detect and block concurrent active sessions for the same user on the same channel. If a new session is established for a user who already has an active session on the same channel, the earlier session must be invalidated. | P1 |

---

## 9. Open Questions & Assumptions

### Open Questions

| ID | Question | Owner |
|---|---|---|
| OQ-01 | What is the maximum number of active reward rules expected per tenant at launch? This determines whether rules are evaluated in-process or require a queue. **[RESOLVED 2026-08 — rules are evaluated in-process; an external event stream and an internal transactional outbox feed a single shared evaluate-and-issue core. Re-open only if per-tenant rule counts or event volume force a queue.]** | Manan / Engineering |
| OQ-02 | Which external event sources will be in scope at launch — and what are their event schemas? Field mapping configuration depends on source schema availability. | Manan / Partner teams |
| OQ-03 | What is the configured timeout for external payment calls (bank API, mobile money)? This must be specified before reconciliation thresholds can be defined. | Manan / Infrastructure |
| OQ-04 | Is there a requirement to display points-to-cash conversion rate to the user before redemption confirmation? This affects the redemption initiation screen. | Manan |
| OQ-05 | What is the expected daily transaction volume per tenant at launch? Required for sizing reconciliation job schedule and rules engine throughput targets. | Manan |
| OQ-06 | Does the rewards-only deployment mode require any form of user registration, or is the user identified entirely by the identifier in the incoming event? **[RESOLVED 2026-08 — deployment mode is load-bearing (`business_type`): in `rewards` mode the user is identified by the identifier carried in the external event and no wallet self-registration is required; `wallet`/`both` modes use phone-first self-registration.]** | Manan / Compliance |
| OQ-07 | What is the notification provider (SMS gateway) for Phase 1 — and does it support delivery receipts? Delivery receipt support affects notification retry logic. | Manan / Infrastructure |
| OQ-08 | Are there regulatory requirements (KYC, AML, transaction reporting) specific to the initial markets that must be accommodated in Phase 1 platform design? | Manan / Legal & Compliance |

### Assumptions

| ID | Assumption |
|---|---|
| A-01 | The platform will be deployed as a modular monolith in Phase 1. All modules run within a single deployable unit. Module extraction into independent services is a Phase 2 decision. |
| A-02 | Keycloak is the identity provider for all administrator and operator access. User-facing authentication (PIN, OTP) is handled by the platform's own identity module. |
| A-03 | The financial ledger is append-only. Balance is always derived from ledger entry summation, with periodic balance snapshots for read performance. |
| A-04 | USSD sessions are serial per user. A single user cannot have two concurrent USSD sessions. This eliminates USSD-specific race conditions on wallet balance. |
| A-05 | External events consumed from Kafka carry a unique `event_id` generated by the source system. The platform relies on this field for deduplication. If the source system does not provide a stable unique ID, a deduplication strategy must be agreed with that source before integration. |
| A-06 | Reward rules are defined as structured data objects, now authored through the admin Campaigns UI. Rule changes take effect at runtime without a code deployment. |
| A-07 | The redemption provider exposes a status check endpoint that can be polled for the outcome of a previously submitted redemption request. |
| A-08 | South Africa is the primary market for Phase 1. Multi-market, multi-currency, and multi-language requirements are addressed through tenant configuration, not parallel codebases. |
| A-09 | Each currency is a distinct account; money is never summed or converted across currencies anywhere (ledger, limits, analytics, mobile). Real-time FX remains out of scope. |
| A-10 | The operator cash float is pre-funded from the bank and kept topped up; float-sourced funding fails closed when the float is empty. Partner funding is fail-open on the max-balance ceiling (an accepted product decision) while overdraft and fail-closed pricing/limits still apply. |
| A-11 | Reward evaluation and issuance are strictly post-commit and fail-open: a reward failure never affects the underlying money transaction. |

---

*End of document — Wallet & Rewards Platform PRD v1.4 (as-built, augmented 2026-08-05 from v1.3).*
