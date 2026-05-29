# Sasai Wallet & Rewards Platform — Vision & Strategy

> **Document type:** Product Vision
> **Version:** 0.1 — Genesis Init
> **Date:** 2026-05-28
> **Status:** Draft
> **Owner:** Manan — Sasai Fintech

---

## 1. What we're building

Sasai Fintech moves money across the African diaspora corridor. Today, every transaction is one-and-done — a remittance arrives in a third-party mobile money wallet, the relationship ends, and the user has no reason to return until they need to send again. This platform changes that.

We're building two capabilities that can ship together or independently:

A **wallet** — a stored-value account inside the Sasai ecosystem. Money received from a remittance lands here, lives here, and can be spent here: P2P transfers, bill payments, top-ups, redemptions. Sasai stops being a corridor and becomes a financial home.

A **rewards and engagement engine** — a configurable rule-based system that watches transaction activity (internal or from external partner systems via Kafka) and issues rewards: points, cashback, tier upgrades, badges, challenges. It can be deployed standalone as "rewards-only" mode for partners who already run their own rails.

Together they turn transient users into a sticky base, give partners a loyalty layer they can plug into, and feed WebEngage the behavioural signal it needs to re-engage at the right moment.

## 2. Mission

Give every Sasai user a reason to stay between remittances — through a wallet they can spend from and a rewards engine that recognises every meaningful action they take.

## 3. North Star metric

**Monthly active engaged users** — defined as users who completed at least one wallet transaction OR earned at least one reward event in the trailing 30 days. This excludes one-off remittance recipients who never returned, and weights internal engagement equally with externally-sourced events.

Rejected alternatives:
- *Transaction volume* — flatters us when remittances spike, doesn't measure stickiness.
- *Points issued* — operator can game this by lowering thresholds.
- *DAU* — too noisy for a financial product with weekly/biweekly cadence.

## 4. Strategic pillars

| Pillar | Why it matters |
|---|---|
| **A wallet that holds value** | Without stored value, every user is transient. The wallet is the substrate on which all engagement compounds. |
| **A rewards engine partners can plug into** | Sasai's white-label and partner-embedded businesses need a shared loyalty layer. Building one engine that serves all of them, internal and external, multiplies leverage. |
| **Behavioural signal for re-engagement** | WebEngage and future engagement tools are only as good as the signal they receive. Streak-broken, milestone-approaching, points-expiring events let us intervene with precision instead of generic blasts. |
| **Multi-tenant, multi-product foundation** | Sasai will expand into insurance and savings. The same identity, ledger, and rewards primitives should serve them all without rebuilds. |

## 5. Target users

### Primary persona — Diaspora remittance recipient
Beneficiary in Sub-Saharan Africa (initially South Africa, ZAR) who receives money from a relative abroad through Sasai. Today: cashes out immediately because there's no reason not to. With the wallet: holds value, pays bills, sends within the network, accumulates points.

### Primary persona — Diaspora sender
Sasai user abroad sending to family at home, multiple corridors per month. Today: chooses Sasai based on price alone, jumps to competitors. With rewards: streak rewards, tier benefits, referral bonuses make Sasai sticky beyond price.

### Operational persona — Platform administrator
Sasai operations staff (finance reviewer, support agent, platform admin) running daily reconciliation, rule configuration, user lookups, and audit. Today: spreadsheets, manual queries. With admin UI: command-palette navigation, drawer-based workflows, audit log front-and-centre.

## 6. Competitive landscape

> RESEARCH NEEDED: name and assess Mukuru, Mama Money, WorldRemit, Chipper Cash on (a) stored-value capability in beneficiary market, (b) loyalty programme depth, (c) partner-embedded rewards. Fill in before sharing externally.

Initial read:
- **Mukuru** — strong corridor reach, no rewards layer, no stored value in destination wallet.
- **Mama Money** — community brand, cash-out model.
- **Cash App / Chime (mature markets)** — what a "stored value + rewards" experience looks like at scale. Reference for UX bar.

How we win: Sasai is the only operator combining (a) existing corridor presence in our markets, (b) a stored-value wallet at destination, and (c) a partner-pluggable rewards engine. The combination is the moat — not any individual capability.

## 7. Success metrics

| Metric | 90 days | 6 months | 12 months |
|---|---|---|---|
| Monthly active engaged users (MAEU) | — | — | — |
| % of remittance recipients holding wallet balance >7 days | — | — | — |
| Reward events per active user / month | — | — | — |
| Partner tenants live on rewards-only mode | 0 | 1 | 3 |
| Reconciliation success rate (auto-resolved / total) | 95% | 98% | 99% |

> ACTION NEEDED: fill targets. 90-day should be achievable with private beta cohort; 12-month ambitious but grounded. Don't leave blank — even rough numbers force alignment.

## 8. Out of scope (Phase 1)

- Real-time FX conversion. Multi-currency within one wallet.
- Card issuance (Visa / Mastercard).
- E-money / banking licence functions.
- Automated bank file generation, settlement instruction execution.
- Rule-based fraud detection and AML transaction monitoring (limits + thresholds only).
- Merchant-initiated recurring billing.
- Graphical rule builder admin UI (rules configured by data objects in Phase 1; UI builder is what we're spec'ing in `04-ui-layouts.md` for Phase 1.5).
- Customer support tooling (case management, disputes).
- Cross-border remittance origination (this platform receives, not initiates).
- Points expiry rules and promotional campaign authoring (deferred).

(Aligned with PRD §5.)
