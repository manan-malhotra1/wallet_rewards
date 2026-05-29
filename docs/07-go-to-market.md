# Go-to-Market Plan

> **Document type:** Go-to-Market
> **Version:** 0.1
> **Date:** 2026-05-28
> **Status:** Draft

---

## 1. Launch strategy

### Phase 1 — Internal pilot (Weeks 1–6)
- **Audience:** Sasai-ZA tenant only. Internal Sasai staff as first wallet users.
- **Goal:** Validate ledger correctness, reconciliation flow, admin UI usability in a real environment.
- **Success metric:** 100% reconciliation auto-resolve rate; zero ledger imbalance incidents; positive operator feedback on the admin UI.

### Phase 2 — Closed beta with a curated user cohort (Weeks 7–14)
- **Audience:** 50–200 selected diaspora users (existing Sasai remittance senders + their beneficiaries) in the ZA corridor.
- **Goal:** Validate that beneficiaries hold balance (rather than cash-out immediately), and that the rewards loop drives repeat sends.
- **Success metric:** ≥ 30% of beneficiaries hold any wallet balance > 7 days; ≥ 1 reward event per active sender per month.

### Phase 3 — Partner-embedded rewards-only (Weeks 15–24)
- **Audience:** One white-label partner tenant deployed in `rewards-only` mode against their existing transaction system.
- **Goal:** Prove the multi-tenant architecture and event-driven rules engine works for external partners.
- **Success metric:** Partner rules firing on partner events with zero internal Sasai code change.

### Phase 4 — Open launch in primary corridor
- Triggered when Phase 2 metrics sustain for 4 consecutive weeks.

---

## 2. Pricing & monetisation

This is an internal Sasai platform, not directly monetised. Value capture happens via:

1. **Retention uplift** — wallet users send more frequently than cash-out users (validate in Phase 2).
2. **Reduced acquisition cost** — referral rewards (Pay-PRD-0622) lower CAC vs. paid acquisition.
3. **Partner revenue** — rewards-only mode offered as a paid platform service to partners (Phase 3+).

> ACTION NEEDED: define partner pricing model before Phase 3. Options: (a) flat platform fee, (b) per-active-user, (c) revenue share on retained users. Each has different incentive implications.

---

## 3. Growth channels

| Channel | Why it fits | Effort | Expected impact |
|---|---|---|---|
| Existing Sasai remittance sender base | Captive audience, zero CAC | Low | High (Phase 2 onward) |
| Diaspora WhatsApp / Facebook groups | Where the diaspora communities organically gather | Medium | Medium |
| Referral rewards (Pay-PRD-0622) | Self-reinforcing once the rewards programme works | Built-in | High (compounds in Phase 3+) |
| Partner channels (rewards-only) | Each partner brings their existing user base | High | High (multiplier) |
| Paid social in target markets | Slow-burn, brand-building | High | Low–Medium initially |

---

## 4. Key success metrics

| Stage | Metric | Phase 2 target | Phase 4 target |
|---|---|---|---|
| Activation | % of new wallet holders who complete first transaction in 7d | — | — |
| Retention | Week-4 retention of beneficiaries | ≥ 30% | ≥ 50% |
| Engagement | Median reward events per active user per month | ≥ 1 | ≥ 4 |
| Operational | Reconciliation auto-resolve rate | ≥ 95% | ≥ 99% |
| Partner | Live partner tenants in rewards-only mode | 0 | 3 |

> ACTION NEEDED: set Phase 2 targets in collaboration with the Sasai data team.

---

## 5. Launch risks

| Risk | Mitigation |
|---|---|
| Beneficiaries cash out immediately, defeating the wallet thesis | Phase 2 explicitly measures hold time; if < 30% hold > 7d, the rewards programme rules need redesign |
| External event sources don't deliver proof-of-origin reliably | Pay-PRD-0495 mandates rejection and audit-log on integrity failure — partners must conform before launch |
| Operator UI is slower than Excel for daily tasks | Heavy keyboard + command-palette focus in admin UI; sit-down validation with finance reviewer before Phase 1 sign-off |
| Reward velocity becomes a fraud vector | NFR-0270 flags unusual reward volumes for review; not auto-block in Phase 1 |
| Compliance ask after launch forces re-architecture | OQ-08 must be answered before Phase 2 |

---

## 6. Comms plan (per phase)

- **Phase 1** — internal Slack channel, weekly demo to Sasai leadership.
- **Phase 2** — onboarding emails to selected beneficiaries; in-app tutorial; WhatsApp support channel.
- **Phase 3** — partner co-launch announcement; case study post-Phase 3 close.
- **Phase 4** — broader diaspora corridor announcement, paid retargeting of existing remittance senders.
