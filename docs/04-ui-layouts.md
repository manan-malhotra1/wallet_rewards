# Sasai Wallet & Rewards Platform — Admin UI Layouts

> **Document type:** UI Specification
> **Version:** 0.1
> **Date:** 2026-05-28
> **Scope:** Next.js 16 Admin UI (mobile app deferred to Phase 2)
> **Design references:** Linear, Stripe Dashboard, Mercury Workspace

---

## 1. Design philosophy

The admin UI serves platform operators (finance reviewers, support agents, platform admins) who spend hours daily inside it. Every decision optimises for **information density**, **keyboard speed**, and **zero-ambiguity state**. We borrow from Linear and Stripe — not Notion, not marketing surfaces.

### Core principles

1. **Density over decoration.** Tables, not cards. Compact rows. Power users scan, they don't browse.
2. **Keyboard is faster than mouse.** Command palette (⌘K) routes anywhere. J/K to move between rows. ⌘↵ to confirm. ESC to dismiss.
3. **Drawer over navigation.** Detail views open in a slide-over drawer or an inspector pane — never lose your place in a table.
4. **Optimistic UI for non-financial actions.** For ledger writes, show pending state explicitly until server confirms.
5. **Status is always visible.** Every transaction, redemption, segment, rule has a coloured pill. Never guess.
6. **Dark is default.** Light is opt-in via system preference. Both must work at WCAG AA.

---

## 2. Design tokens

### 2.1 Colour scale (oklch)

```css
/* Surfaces (dark — default) */
--surface-0: oklch(0.18 0.01 240);   /* page bg */
--surface-1: oklch(0.22 0.01 240);   /* card */
--surface-2: oklch(0.26 0.01 240);   /* hover */
--surface-3: oklch(0.32 0.01 240);   /* selected */
--border:    oklch(0.30 0.01 240);

/* Text */
--text-1: oklch(0.96 0 0);           /* primary */
--text-2: oklch(0.75 0 0);           /* secondary */
--text-3: oklch(0.55 0 0);           /* muted */

/* Brand (Sasai navy + teal accent, lifted for dark mode) */
--brand:    oklch(0.55 0.16 235);
--accent:   oklch(0.75 0.13 200);

/* Status */
--success:  oklch(0.72 0.18 145);    /* COMPLETED */
--warning:  oklch(0.78 0.16 75);     /* PENDING / MANUAL_REVIEW */
--danger:   oklch(0.65 0.22 25);     /* FAILED / REVERSED */
--info:     oklch(0.70 0.13 235);    /* INFO banner */

/* Financial semantics */
--credit:   oklch(0.72 0.18 145);    /* CREDIT — green */
--debit:    oklch(0.65 0.22 25);     /* DEBIT — red */
--points:   oklch(0.78 0.16 75);     /* Points — amber */
```

### 2.2 Typography

| Token | Value | Use |
|---|---|---|
| `font-sans` | Geist Sans | UI text |
| `font-mono` | Geist Mono | IDs, amounts, JSON, code |
| `text-display` | 24px / 28px / 600 | Page title |
| `text-h1` | 18px / 24px / 600 | Section heading |
| `text-h2` | 14px / 20px / 600 | Card title |
| `text-body` | 13px / 18px / 400 | Default |
| `text-caption` | 12px / 16px / 400 | Metadata |
| `text-mono-sm` | 12px / 16px mono | IDs, references |
| `text-num-lg` | 22px / 28px / 600 tabular-nums | Big amount displays |

### 2.3 Spacing

4px base unit. Tables use 4px vertical, 12px horizontal. Cards use 16px padding.

### 2.4 Status pills

| State | Visual | Used by |
|---|---|---|
| COMPLETED | `● Completed` green | Transactions, redemptions |
| PENDING | `● Pending` amber, pulsing | Transactions, redemptions |
| FAILED | `● Failed` red | Transactions |
| REVERSED | `● Reversed` grey | Transactions |
| MANUAL_REVIEW | `● Needs review` red | Redemptions, fraud signal |
| PROCESSING | `⟳ Processing` amber spinner | Redemptions |
| ACTIVE / DRAFT / INACTIVE | green / grey / muted | Rules, segments, tenants |

Compact form: dot only in dense tables, full pill on detail screens.

---

## 3. AppShell — global layout

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ [≡] Sasai·Wallet  [▼ Sasai-ZA]      ⌘K Search...        [🔔 3]  [User ▼]       │ ← Topbar 48px
├──────────┬──────────────────────────────────────────────────────────────────────┤
│ OPERATIONS│                                                                      │
│ ▢ Dashboard│   Page Content                                                       │
│ ▢ Users    │   ┌─────────────────────────────────────────────────────────────┐  │
│ ▢ Merchants│   │ Page header + tabs                                          │  │
│ ▢ Transactions│ ├─────────────────────────────────────────────────────────────┤  │
│ ▢ Recon ⓘ12│   │ Filter bar                                                  │  │
│            │   ├─────────────────────────────────────────────────────────────┤  │
│ CONFIG     │   │                                                              │  │
│ ▢ Rules    │   │ Table / cards / detail view                                  │  │
│ ▢ Segments │   │                                                              │  │
│ ▢ Limits   │   │                                                              │  │
│ ▢ Pricing  │   │                                                              │  │
│ ▢ Redemption│  │                                                              │  │
│ ▢ Tenants  │   └─────────────────────────────────────────────────────────────┘  │
│            │                                                                      │
│ AUDIT      │                                                                      │
│ ▢ Audit log│                                                                      │
│ ▢ Events   │                                                                      │
│            │                                                                      │
│ [Settings] │                                                                      │
└──────────┴──────────────────────────────────────────────────────────────────────┘
   ↑ Sidebar 240px (collapsible to 56px icon-only)
```

### Topbar (left → right)

- Sidebar toggle (≡)
- Logo + product name
- **Tenant switcher** — combobox showing current tenant; ⌘T to focus
- **Global search** — ⌘K opens command palette (primary navigation)
- Notification bell with unread count (fraud signals NFR-0270, MANUAL_REVIEW queue, sweep failures)
- User menu (Keycloak identity, role displayed)

### Sidebar sections

- **OPERATIONS** — daily-use screens. Each shows badge count where relevant (e.g. Reconciliation when PENDING > 0).
- **CONFIGURATION** — setup screens.
- **AUDIT** — read-only logs.

---

## 4. Command palette (⌘K)

The single most important UX primitive. Mirrors Linear's command bar.

```
┌───────────────────────────────────────────────────────────────┐
│ ⌘K  Type a command or search...                          ESC  │
├───────────────────────────────────────────────────────────────┤
│ NAVIGATE                                                       │
│   →  Go to Dashboard                                  ⌘1       │
│   →  Go to Reconciliation (12 pending)                ⌘5       │
│   →  Go to Rules                                                │
│                                                                 │
│ SEARCH                                                          │
│   👤  User by phone +27...                                      │
│   💳  Transaction by ID                                         │
│   🎯  Rule by name                                              │
│                                                                 │
│ ACTIONS                                                         │
│   +  Create new rule                                            │
│   +  Create new segment                                         │
│   +  Suspend user (requires confirm)                            │
│                                                                 │
│ TENANT                                                          │
│   ⇄  Switch tenant → Sasai-ZA                          ⌘T       │
│   ⇄  Switch tenant → Sasai-KE                                   │
└───────────────────────────────────────────────────────────────┘
```

- Fuzzy match across page names, user identifiers (phone / email / account / card), txn IDs, rule names
- Recent commands surface first
- ↵ executes; arrows navigate; ESC closes
- Available on every page

---

## 5. Screens

### 5.1 Dashboard (`/dashboard`)

Single-glance health of the active tenant.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Overview · Sasai-ZA                              Today · Last 7d · 30d  │
├─────────────────────────────────────────────────────────────────────────┤
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐         │
│ │ TXNS TODAY  │ │ FAILED RATE │ │ PENDING     │ │ ACTIVE USERS│         │
│ │   12,481    │ │    0.8%     │ │     12 ⚠   │ │    8,243    │         │
│ │ ▲ 4.2%      │ │ ▼ 0.3pp     │ │ sweep 4m ago│ │ ▲ 1.1%      │         │
│ └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘         │
│                                                                          │
│ Transactions by status (24h)        Rewards issued (24h)                │
│ ┌─────────────────────────────────┐ ┌─────────────────────────────┐    │
│ │ ▇▇▇▇▇▇▇▇▇▇▇▇▇▇ COMPLETED 98.2% │ │ Points: 1.2M issued         │    │
│ │ ▇ PENDING 0.5%                  │ │ Cashback: ZAR 18,400        │    │
│ │ ▇ FAILED 0.8%                   │ │ Top rule: Weekly P2P streak │    │
│ │ ▇ REVERSED 0.5%                 │ │ (286 fires)                 │    │
│ └─────────────────────────────────┘ └─────────────────────────────┘    │
│                                                                          │
│ Alerts                                                                  │
│ ⚠ Fraud signal — user 7a3f… exceeded reward velocity threshold     ►   │
│ ⚠ 3 redemptions in MANUAL_REVIEW                                   ►   │
└─────────────────────────────────────────────────────────────────────────┘
```

**Acceptance criteria**
- KPI cards refresh every 30s without page reload (server actions + Suspense)
- "Pending" card is clickable → routes to `/reconciliation`
- Date range toggle re-fetches via server action
- Alerts are clickable into the relevant detail view

---

### 5.2 Users (`/users`)

Identifier-first lookup (Pay-PRD-0060). Drawer detail.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Users                                              [+ Register user]    │
├─────────────────────────────────────────────────────────────────────────┤
│ All · Active · Suspended · Closed                                       │
├─────────────────────────────────────────────────────────────────────────┤
│ [🔎 Phone / Email / Account / Card]   Tier ▼   Created ▼   Status ▼     │
├─────────────────────────────────────────────────────────────────────────┤
│ ☐ │ Identifier        │ User ID       │ Status   │ Tier   │ Created    │
│───┼───────────────────┼───────────────┼──────────┼────────┼────────────│
│ ☐ │ +27 82 555 0142   │ usr_7a3f…     │ ● Active │ Silver │ Mar 14     │
│ ☐ │ +27 71 999 0021   │ usr_b21c…     │ ● Active │ Bronze │ Apr 02     │
│ ☐ │ +27 84 222 4400   │ usr_9d8e…     │ ◐ Susp.  │ Gold   │ Jan 19     │
│ ☐ │ jane@example.com  │ usr_3f1a…     │ ● Active │ Bronze │ Apr 19     │
│                                                                          │
│ ◄ 1 2 3 … 48 ►                                          50 per page     │
└─────────────────────────────────────────────────────────────────────────┘
```

**Drawer (slide-over from right, 480px)**

```
                                  ┌──────────────────────────────────────┐
                                  │ usr_7a3f8c…                       ×  │
                                  │ +27 82 555 0142 · ● Active · Silver  │
                                  ├──────────────────────────────────────┤
                                  │ IDENTIFIERS                          │
                                  │ Phone  +27 82 555 0142   ✓ Verified  │
                                  │ Email  jane@email.com    ✓ Verified  │
                                  │ Acct   ZA-001-887-2210   — internal  │
                                  │                       [+ Add ID]     │
                                  │ ──────────────────────────────────── │
                                  │ KYC                                  │
                                  │ Status         Verified (Tier 2)     │
                                  │ Date of birth  1989-04-21            │
                                  │ Profile        Jane Mokoena          │
                                  │                                       │
                                  │ ACCOUNTS                             │
                                  │ Wallet ZAR    R 1,284.50 available   │
                                  │ Points        4,800 pts              │
                                  │                                       │
                                  │ ACTIVITY (last 5)                    │
                                  │ Apr 28  P2P  +R 200   Completed      │
                                  │ Apr 27  Bill -R 50    Completed      │
                                  │ Apr 25  Bill -R 120   Failed         │
                                  │                                       │
                                  │ [View full activity]  [Suspend]      │
                                  └──────────────────────────────────────┘
```

**Acceptance criteria**
- Search resolves any identifier type to a single user via Pay-PRD-0060
- Drawer closes with ESC; URL updates to `?user_id=…` for shareable links
- Suspend triggers a confirm modal with required reason field (audit-logged per NFR-0250)
- "Suspend" hidden if operator lacks the `support-agent`+ role

---

### 5.3 Rules (`/rules`) — the central engine

The most complex screen. Must support **all 7 rule types**: milestone, streak, first-time, value-based, composite, campaign, referral — plus segments, bonus multipliers, and `stop_after_n_triggers`.

**List view**

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Rules                                                  [+ New rule ▾]   │
├─────────────────────────────────────────────────────────────────────────┤
│ All (24) · Active (18) · Draft · Inactive · Expired                     │
├─────────────────────────────────────────────────────────────────────────┤
│ Type ▼   Segment ▼   Search rules...                                    │
├─────────────────────────────────────────────────────────────────────────┤
│ Name                       │ Type      │ Trigger     │ Reward   │ Fires│
│────────────────────────────┼───────────┼─────────────┼──────────┼──────│
│ Weekly P2P streak          │ Streak    │ P2P × 4 wks │ 200 pts  │ 286  │
│ Bill-pay 5 times this month│ Milestone │ Bill × 5    │ 50 pts   │ 1,042│
│ First top-up               │ First-time│ Top-up      │ R 25     │ 412  │
│ High-value remittance      │ Value     │ Top-up ≥1k  │ 100 pts  │ 89   │
│ Refer-a-friend (referrer)  │ Referral  │ —           │ 500 pts  │ 18   │
│ Send + Pay this month      │ Composite │ P2P AND Bill│ 250 pts  │ 36   │
│ May launch campaign        │ Campaign  │ May 1–31    │ 2× pts   │ 1,294│
└─────────────────────────────────────────────────────────────────────────┘
```

**Create rule — step 1 (type picker)**

```
┌───────────────────────────────────────────────────────────────┐
│  Create rule  ›  Choose a rule type                       ✕   │
├───────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐  │
│  │ ✓ Milestone     │ │   Streak        │ │   First-time    │  │
│  │ User completes N│ │ N consecutive   │ │ First time user │  │
│  │ qualifying txns │ │ periods, must   │ │ does an action  │  │
│  │ — counter resets│ │ not break       │ │ — fires once    │  │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘  │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐  │
│  │   Value-based   │ │   Composite     │ │   Campaign      │  │
│  │ Min txn amount  │ │ Multiple conds  │ │ Time-boxed rule │  │
│  │ as a condition  │ │ joined AND / OR │ │ start–end dates │  │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘  │
│  ┌─────────────────┐                                          │
│  │   Referral      │                                          │
│  │ Referrer reward │                                          │
│  │ on referred act │                                          │
│  └─────────────────┘                                          │
└───────────────────────────────────────────────────────────────┘
```

**Create rule — step 2 (configure, form changes by type)**

```
┌───────────────────────────────────────────────────────────────────────┐
│  New rule · Milestone                                             ✕   │
├───────────────────────────────────────────────────────────────────────┤
│  Name *                  [ Weekly P2P milestone                    ]  │
│  Description             [                                         ]  │
│                                                                        │
│  TRIGGER                                                              │
│  Transaction type *      [ P2P                              ▼      ]  │
│  Count threshold *       [ 5                                       ]  │
│  Time window *           ○ Lifetime  ◉ Calendar month  ○ Rolling 7d   │
│  Min amount (optional)   [ R          ]   (value-based condition)     │
│                                                                        │
│  REWARD                                                               │
│  Reward type *           ◉ Points    ○ Cashback                       │
│  Reward value *          [ 200       ] pts                            │
│                                                                        │
│  LIMITS                                                               │
│  Stop after N triggers   [ 0 = unlimited                           ]  │
│  Reset counter on fire   [✓] (uncheck for "once per user")            │
│                                                                        │
│  AUDIENCE                                                             │
│  Segment (optional)      [ All users                        ▼      ]  │
│                          (only members of segment progress)           │
│                                                                        │
│  SUMMARY                                                              │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ When a user completes 5 P2P transactions in a calendar month,  │  │
│  │ credit 200 points. Counter resets each month. Unlimited triggers│  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│                              [Save as draft]  [Activate rule]         │
└───────────────────────────────────────────────────────────────────────┘
```

**Acceptance criteria**
- Live summary sentence regenerates as form changes
- Form validates against PRD constraints (e.g. streak rules require `streak_units` + `streak_unit_window`)
- "Activate rule" disabled until required fields valid
- "Save as draft" creates with `status='inactive'`
- Edit existing rule reuses same form

---

### 5.4 Segments (`/segments`)

Two segment types — uploaded list and behavioural (Module 15).

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Segments                                            [+ New segment ▾]   │
│                                                     Upload list / Build │
├─────────────────────────────────────────────────────────────────────────┤
│ Name                  │ Type        │ Members │ Bound rules │ Updated  │
│───────────────────────┼─────────────┼─────────┼─────────────┼──────────│
│ Diaspora-SA-active    │ Behavioural │ ~3,200  │ 4 rules     │ Live      │
│ March-newsletter-list │ Uploaded    │ 1,842   │ 2 rules     │ 12d ago   │
│ Gold-tier             │ Behavioural │ ~482    │ 6 rules     │ Live      │
└─────────────────────────────────────────────────────────────────────────┘
```

**Behavioural builder**

```
┌───────────────────────────────────────────────────────────────────────┐
│  Build behaviour segment                                          ✕   │
├───────────────────────────────────────────────────────────────────────┤
│  Name [ Diaspora-SA-active                                         ]  │
│                                                                        │
│  Match users where  ◉ ALL conditions are true   ○ ANY                 │
│                                                                        │
│  ┌───────────────────────────────────────────────────────────────┐    │
│  │ Last transaction date    [is after  ▼]  [30 days ago      ] × │    │
│  ├───────────────────────────────────────────────────────────────┤    │
│  │ Total txn count          [≥          ▼]  [5               ] × │    │
│  ├───────────────────────────────────────────────────────────────┤    │
│  │ Current tier             [is         ▼]  [Silver, Gold ▼  ] × │    │
│  ├───────────────────────────────────────────────────────────────┤    │
│  │                                                  [+ Add condition] │
│  └───────────────────────────────────────────────────────────────┘    │
│                                                                        │
│  Estimated members  ~3,200  [Re-estimate]                             │
│                                                                        │
│                                          [Save draft]  [Activate]     │
└───────────────────────────────────────────────────────────────────────┘
```

Upload variant: drop CSV, preview, show resolution counts (Pay-PRD-0910).

---

### 5.5 Reconciliation (`/reconciliation`)

The operator's daily-driver — Pay-PRD-0750 sweep queue + manual review.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Reconciliation                                       Next sweep · 4m    │
├─────────────────────────────────────────────────────────────────────────┤
│ Pending (12) · Manual review (3) · Recently resolved · Sweep log        │
├─────────────────────────────────────────────────────────────────────────┤
│ Type ▼   Age ▼   Tenant ▼              [↻ Sweep now] [Resolve selected] │
├─────────────────────────────────────────────────────────────────────────┤
│☐│ Txn ID          │ Type    │ Amount  │ Age   │ Retries │ Status        │
│─┼─────────────────┼─────────┼─────────┼───────┼─────────┼───────────────│
│☐│ txn_8a3f…       │ P2P     │ R 200   │ 12m   │ 1/3     │ ⏳ Pending    │
│☐│ txn_1c4d…       │ Top-up  │ R 1,500 │ 28m   │ 2/3     │ ⏳ Pending    │
│☐│ red_2e9b…       │ Redeem  │ 5,000pt │ 1h    │ 3/3     │ ⚠ Manual rev. │
│☐│ txn_99af…       │ Bill    │ R 80    │ 4m    │ 0/3     │ ⏳ Pending    │
└─────────────────────────────────────────────────────────────────────────┘
```

**Right inspector pane (320px, persistent — never navigates away)**

```
  ┌────────────────────────────────────┐
  │ txn_8a3f8c…                     ×  │
  │ P2P · R 200 · Pending              │
  ├────────────────────────────────────┤
  │ Initiated by  usr_7a3f…            │
  │ To recipient  usr_b21c…            │
  │ Idempotency   wd_5f8a2c…           │
  │ External ref  ZA-MM-89432          │
  │ Created       12 min ago           │
  │                                     │
  │ STATUS CHECK LOG                   │
  │ 09:14 → polled provider → no data  │
  │ 09:24 → polled provider → pending  │
  │ Next  09:34 (auto)                 │
  │                                     │
  │ ACTIONS                            │
  │ [Force status check]  [Reverse]    │
  │ [Mark manual review]               │
  └────────────────────────────────────┘
```

**Acceptance criteria**
- Action buttons require operator role + confirm modal
- "Reverse" writes a new ledger entry (Pay-PRD-0780), never edits existing
- "Force status check" calls provider's status endpoint, surfaces response inline
- MANUAL_REVIEW item requires a resolution-notes textarea before closing out

---

### 5.6 Limits / Pricing — config tables

Editable tables, per-tenant scoping (Pay-PRD-0380, Pay-PRD-0430).

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Limits · Sasai-ZA                                  [+ Add config]       │
├─────────────────────────────────────────────────────────────────────────┤
│ Transaction │ Account     │ Min (ZAR)│ Max (ZAR) │ Daily ct│ Daily val  │
│─────────────┼─────────────┼──────────┼───────────┼─────────┼────────────│
│ P2P         │ Wallet ZAR  │ 10       │ 5,000     │ 10      │ 25,000     │
│ Bill        │ Wallet ZAR  │ 5        │ 10,000    │ —       │ —          │
│ Top-up      │ Wallet ZAR  │ 50       │ 50,000    │ 5       │ 100,000    │
│ Redeem      │ Points      │ 100      │ 50,000    │ 2       │ —          │
└─────────────────────────────────────────────────────────────────────────┘
```

Inline edit on click. Save = audit log entry (NFR-0250). Pricing screen identical shape (fixed_fee, variable_fee_pct).

---

### 5.7 Redemption (`/redemption`)

Provider config + MANUAL_REVIEW queue (Pay-PRD-0790).

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Redemption                                                              │
├─────────────────────────────────────────────────────────────────────────┤
│ Providers · Queue · Manual review (3) · History                         │
├─────────────────────────────────────────────────────────────────────────┤
│ Provider           │ Status │ Max retries │ Interval│ Escalate│ Actions │
│────────────────────┼────────┼─────────────┼─────────┼─────────┼─────────│
│ Mukuru Voucher     │ ● Live │ 3           │ 5 min   │ 60 min  │ [Edit]  │
│ MTN Airtime ZA     │ ● Live │ 5           │ 2 min   │ 30 min  │ [Edit]  │
│ Vodacom Airtime    │ ◐ Test │ 3           │ 5 min   │ 60 min  │ [Edit]  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 5.8 Tenants (`/tenants`)

Top-of-stack config. Deployment mode is the most consequential switch.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Tenants                                              [+ Create tenant]  │
├─────────────────────────────────────────────────────────────────────────┤
│ Name        │ Mode          │ Currency │ Status   │ Created            │
│─────────────┼───────────────┼──────────┼──────────┼────────────────────│
│ Sasai-ZA    │ Wallet        │ ZAR      │ ● Active │ Jan 04 2026        │
│ Sasai-KE    │ Wallet        │ KES      │ ● Active │ Feb 12 2026        │
│ Econet-ZW   │ Rewards only  │ —        │ ● Active │ Mar 22 2026        │
└─────────────────────────────────────────────────────────────────────────┘
```

Detail page = tabs: **General · Config keys · Roles · Event sources · API keys**.

---

### 5.9 Audit (`/audit`)

Read-only, filterable. Every config change captured with before/after diff (NFR-0250).

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Audit log                                                                │
├─────────────────────────────────────────────────────────────────────────┤
│ Actor ▼  Action ▼  Entity ▼  Date range ▼              [Export CSV]    │
├─────────────────────────────────────────────────────────────────────────┤
│ Time     │ Actor       │ Action          │ Entity            │         │
│──────────┼─────────────┼─────────────────┼───────────────────┼─────────│
│ 09:23:11 │ manan@…     │ rule.activated  │ rule_4a8e…         │ View ► │
│ 09:18:02 │ system      │ recon.swept     │ 8 transactions     │ View ► │
│ 09:15:44 │ priya@…     │ user.suspended  │ usr_7a3f…          │ View ► │
└─────────────────────────────────────────────────────────────────────────┘
```

Click → drawer with: actor identity + IP, action timestamp, before state (JSON, diff-highlighted), after state (JSON, diff-highlighted).

---

## 6. Component inventory

Built on shadcn/ui + Radix primitives. Tailwind for layout.

| Component | Purpose |
|---|---|
| `<AppShell>` | Sidebar + topbar + main + optional inspector |
| `<CommandPalette>` | ⌘K omnibox (cmdk library) |
| `<DataTable>` | Sortable, multi-select, dense table (TanStack Table) |
| `<StatusPill>` | Dot + label, dense or full variant |
| `<Drawer>` | Right slide-over, ESC to close |
| `<Inspector>` | Persistent right pane |
| `<Money>` | Tabular-nums monospace amount with currency code |
| `<Points>` | Like Money but for points |
| `<IdentifierInput>` | Resolves phone / email / account / card to user |
| `<TenantSwitcher>` | Combobox; persists selection per operator |
| `<KbdHint>` | `⌘K` style key chip |
| `<DiffViewer>` | JSON before/after diff (audit) |
| `<AuditCallout>` | "audit-logged" hint near destructive actions |
| `<ToastQueue>` | Bottom-right, max 3 stacked, dismissable |

---

## 7. Empty / loading / error patterns

**Empty (first time)**

```
┌─────────────────────────────────────────┐
│              ⚪                          │
│         No rules yet                    │
│  Rules trigger rewards when users meet  │
│         configured conditions.           │
│                                          │
│   [+ Create your first rule]  [Docs]    │
└─────────────────────────────────────────┘
```

**Empty (filtered, no results)** — "No rules match these filters" + clear-filters button.

**Loading** — skeleton rows for tables. Spinners only on action buttons during submit.

**Error** — inline banner with retry; never crash the table. Toast for action failures with full error code.

---

## 8. Keyboard reference

| Key | Action |
|---|---|
| `⌘K` | Open command palette |
| `⌘T` | Focus tenant switcher |
| `⌘/` | Show shortcut cheat sheet |
| `J` / `K` | Next / previous row in tables |
| `↵` | Open selected row drawer |
| `X` | Toggle row selection |
| `Esc` | Close drawer / palette / modal |
| `G + D` | Go to Dashboard |
| `G + U` | Go to Users |
| `G + R` | Go to Rules |

---

## 9. Implementation order

1. **AppShell + topbar + sidebar + command palette** — blocks everything else
2. **Auth → Keycloak callback → tenant switcher** — gates everything
3. **Users + drawer** — most reused pattern
4. **Transactions table + status pills** — validates data primitives
5. **Reconciliation queue** — operator's daily driver
6. **Rules list + create flow** — most complex form
7. **Segments builder**
8. **Limits / Pricing / Redemption providers**
9. **Tenants management**
10. **Audit log + diff viewer**

> ACTION NEEDED: validate this order against a real operator's daily workflow before committing to a sprint plan. A 30-minute sit-down with a finance reviewer asking "what do you do first when you sit down?" will reorder this list.
