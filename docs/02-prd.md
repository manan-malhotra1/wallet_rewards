# Product Requirements Document

> **Status:** This file is a pointer + local index. The authoritative PRD is **v1.3** at
> `/Users/manan/Downloads/wallet-platform-prd-v1_0.md`. Update both when the PRD evolves.

## Quick index

| Section | What it covers |
|---|---|
| §1 Purpose | Why this platform exists (corridor stickiness) |
| §2 Problem Statement | Five compounding problems with status-quo |
| §3 Glossary | Domain vocabulary — **read first** before any work |
| §4 Goals | G1–G9 with success indicators |
| §5 Non-Goals | What we will not build in Phase 1 |
| §6 Actors | User, Merchant, Administrator, System, Redemption provider, External event source |
| §7 Functional Requirements | 17 modules — Pay-PRD-0010 through Pay-PRD-1120 |
| §8 Non-Functional Requirements | NFR-0010 through NFR-0280 |
| §9 Open Questions & Assumptions | OQ-01 to OQ-08, A-01 to A-08 |

## Modules

| # | Module | Req range |
|---|---|---|
| 1 | Identity & User Management | 0010–0100 |
| 2 | Account & Wallet Management | 0110–0160 |
| 3 | Ledger | 0170–0240 |
| 4 | Payment Orchestration | 0250–0320 |
| 5 | Limits & Thresholds | 0330–0380 |
| 6 | Pricing Engine | 0390–0430 |
| 7 | Roles & Permissions | 0440–0470 |
| 8 | Event Ingestion & Normalisation | 0480–0520 |
| 9 | Rules Engine | 0530–0624 |
| 10 | Reward Issuance | 0620–0650 |
| 11 | Redemption | 0660–0740 |
| 12 | Reconciliation | 0750–0800 |
| 13 | Notifications | 0810–0850 |
| 14 | Tenant & Platform Configuration | 0860–0900 |
| 15 | Audience Segmentation | 0910–0960 |
| 16 | Rewards Catalog & User Journey | 0970–1050 |
| 17 | External Engagement Event Emission | 1060–1120 |

## How to use this document

1. Before any feature work, **read PRD §3 (Glossary)** — wallet, ledger, idempotency, PENDING, segment, etc. all have precise definitions.
2. For each user story, find the matching `Pay-PRD-XXXX` requirement and treat its acceptance criteria as the test spec.
3. NFRs (§8) bind every module — performance, retention, security. Verify these at design time, not after.
4. Open questions (§9) MUST be resolved before the relevant module ships. Track resolution in this doc.

## Open questions tracking

| ID | Question | Owner | Status |
|---|---|---|---|
| OQ-01 | Max active rules per tenant at launch | Manan + Eng | Open |
| OQ-02 | External event sources in scope at launch | Manan + Partners | Open |
| OQ-03 | Configured timeout for external payment calls | Manan + Infra | Open |
| OQ-04 | Display points-to-cash rate before redemption confirm? | Manan | Open |
| OQ-05 | Expected daily transaction volume per tenant | Manan | Open |
| OQ-06 | User registration required in rewards-only mode? | Manan + Compliance | Open |
| OQ-07 | SMS gateway provider (delivery receipts?) | Manan + Infra | Open |
| OQ-08 | KYC/AML market-specific requirements | Manan + Legal | Open |
