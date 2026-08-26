# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: identifier.spec.ts >> add an account-number identifier, then verify it
- Location: e2e/identifier.spec.ts:23:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('button', { name: 'Add identifier' })
Expected: visible
Timeout: 15000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 15000ms
  - waiting for getByRole('button', { name: 'Add identifier' })

```

```yaml
- complementary:
  - link "Sasai Wallet Admin home":
    - /url: /dashboard
    - img "Sasai"
  - text: Admin
  - navigation:
    - text: Operations
    - list:
      - listitem:
        - link "Dashboard":
          - /url: /dashboard
          - img
          - text: Dashboard
      - listitem:
        - link "Users":
          - /url: /users
          - img
          - text: Users
      - listitem:
        - link "Merchants":
          - /url: /merchants
          - img
          - text: Merchants
      - listitem:
        - link "System wallets":
          - /url: /system-wallets
          - img
          - text: System wallets
      - listitem:
        - link "Commission disbursement":
          - /url: /commission-disbursement
          - img
          - text: Commission disbursement
      - listitem:
        - link "Commission withdrawal":
          - /url: /commission-withdrawal
          - img
          - text: Commission withdrawal
      - listitem:
        - link "Reconciliation":
          - /url: /reconciliation
          - img
          - text: Reconciliation
    - text: Configuration
    - list:
      - listitem:
        - link "Campaigns":
          - /url: /campaigns
          - img
          - text: Campaigns
      - listitem:
        - link "Segments":
          - /url: /segments
          - img
          - text: Segments
      - listitem:
        - link "Multipliers":
          - /url: /multipliers
          - img
          - text: Multipliers
      - listitem:
        - link "Budgets":
          - /url: /budgets
          - img
          - text: Budgets
      - listitem:
        - link "Limits":
          - /url: /limits
          - img
          - text: Limits
      - listitem:
        - link "Step-up PIN":
          - /url: /step-up
          - img
          - text: Step-up PIN
      - listitem:
        - button "Pricing":
          - img
          - text: Pricing
          - img
      - listitem:
        - link "Approvals":
          - /url: /approvals
          - img
          - text: Approvals
      - listitem:
        - link "Redemption":
          - /url: /redemption
          - img
          - text: Redemption
      - listitem:
        - link "Points rates":
          - /url: /redemption-rates
          - img
          - text: Points rates
      - listitem:
        - link "Services":
          - /url: /services
          - img
          - text: Services
      - listitem:
        - link "Instruments":
          - /url: /instruments
          - img
          - text: Instruments
      - listitem:
        - link "User types":
          - /url: /user-types
          - img
          - text: User types
      - listitem:
        - link "Tenants":
          - /url: /tenants
          - img
          - text: Tenants
      - listitem:
        - link "API keys":
          - /url: /api-keys
          - img
          - text: API keys
    - text: Audit
    - list:
      - listitem:
        - link "Audit log":
          - /url: /audit
          - img
          - text: Audit log
      - listitem:
        - link "Events":
          - /url: /events
          - img
          - text: Events
  - text: v1.0.0
- banner:
  - button "Switch tenant":
    - img
    - text: Sasai-ZA ZAR
    - img
  - button "Search users, transactions, rules… ⌘K":
    - img
    - text: Search users, transactions, rules… ⌘K
  - button "Notifications":
    - img
  - button "Toggle theme":
    - img
  - button "admin-test":
    - img
    - text: admin-test
- main:
  - heading "Users" [level=1]
  - paragraph: Look up by phone, email, account, or card identifier.
  - button "Register user":
    - img
    - text: Register user
  - text: Identifier
  - combobox "Identifier": Phone
  - text: Value
  - textbox "Value":
    - /placeholder: +27 82 555 0142
    - text: "+27825550001"
  - button "Lookup":
    - img
    - text: Lookup
  - img
  - heading "Alicia833581 Mokoena833581" [level=2]
  - text: Consumer Active
  - paragraph: "+27825550001"
  - button "Edit":
    - img
    - text: Edit
  - button "Reset PIN":
    - img
    - text: Reset PIN
  - button "Lock login":
    - img
    - text: Lock login
  - button "Lock transactions":
    - img
    - text: Lock transactions
  - paragraph: Wallet balances
  - text: INR 0.00 ZAR 171,810.40
  - button "Show INR wallet"
  - button "Show ZAR wallet"
  - paragraph: Points
  - text: 200 pts
  - paragraph: Transactions
  - text: "20"
  - paragraph: Member since
  - text: Aug 06, 00:42
  - tablist "User detail sections":
    - tab "Personal & KYC"
    - tab "Address & country"
    - tab "KYC documents"
    - tab "Accounts & balances"
    - tab "Transactions"
- region "Notifications alt+T"
- alert
```

# Test source

```ts
  1  | /**
  2  |  * Direct platform-admin action (Epic 27, Stories 27.2 + 27.3) — add then
  3  |  * manually verify an account-number identifier. No maker-checker here: these
  4  |  * are single-admin operations, so this spec runs entirely in the maker context.
  5  |  *
  6  |  * 1. On Alice's user-detail page, open "Add identifier", pick "Account number",
  7  |  *    add a fresh account number → it lands UNVERIFIED, surfacing a "Verify"
  8  |  *    affordance (account numbers verify manually, not via OTP).
  9  |  * 2. Click "Verify" → the row flips to a green "Verified" badge.
  10 |  *
  11 |  * The account number carries a per-run token so re-runs never collide with the
  12 |  * identifier-uniqueness guard.
  13 |  */
  14 | import { test, expect } from "@playwright/test";
  15 | 
  16 | import { STORAGE_STATE } from "../playwright.config";
  17 | 
  18 | test.use({ storageState: STORAGE_STATE.maker });
  19 | 
  20 | const ALICE_PHONE = "+27825550001";
  21 | const ALICE_LOOKUP = `/users?type=phone&value=${encodeURIComponent(ALICE_PHONE)}`;
  22 | 
  23 | test("add an account-number identifier, then verify it", async ({ page }) => {
  24 |   const token = Date.now().toString().slice(-8);
  25 |   const accountNumber = `ZA-E2E-${token}`;
  26 | 
  27 |   await page.goto(ALICE_LOOKUP);
> 28 |   await expect(page.getByRole("button", { name: "Add identifier" })).toBeVisible();
     |                                                                      ^ Error: expect(locator).toBeVisible() failed
  29 | 
  30 |   // ---- Add an unverified account-number identifier -----------------------
  31 |   await page.getByRole("button", { name: "Add identifier" }).click();
  32 |   const dialog = page.getByRole("dialog");
  33 |   await expect(
  34 |     dialog.getByText("Attach a phone, email, or account number"),
  35 |   ).toBeVisible();
  36 | 
  37 |   // Switch the type Select (Radix combobox → listbox option) to Account number.
  38 |   await dialog.getByRole("combobox").click();
  39 |   await page.getByRole("option", { name: "Account number" }).click();
  40 | 
  41 |   await dialog.getByLabel("Value").fill(accountNumber);
  42 |   await dialog.getByRole("button", { name: "Add identifier" }).click();
  43 | 
  44 |   await expect(page.getByText(/identifier added/i)).toBeVisible();
  45 | 
  46 |   // The new row shows the account number with a Verify affordance (unverified).
  47 |   const identRow = page.getByRole("listitem").filter({ hasText: accountNumber });
  48 |   await expect(identRow).toBeVisible();
  49 |   await expect(identRow.getByRole("button", { name: "Verify" })).toBeVisible();
  50 | 
  51 |   // ---- Verify it ----------------------------------------------------------
  52 |   await identRow.getByRole("button", { name: "Verify" }).click();
  53 |   await expect(page.getByText(/identifier verified/i)).toBeVisible();
  54 | 
  55 |   // Row now carries the green "Verified" badge and no longer offers Verify.
  56 |   const verifiedRow = page.getByRole("listitem").filter({ hasText: accountNumber });
  57 |   await expect(verifiedRow.getByText("Verified")).toBeVisible();
  58 | });
  59 | 
```