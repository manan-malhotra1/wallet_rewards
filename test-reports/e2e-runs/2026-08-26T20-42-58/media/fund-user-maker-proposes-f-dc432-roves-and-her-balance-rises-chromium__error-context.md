# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: fund-user.spec.ts >> maker proposes funding Alice; checker approves and her balance rises
- Location: e2e/fund-user.spec.ts:52:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('row').filter({ hasText: 'Financial wallet' }).filter({ hasText: 'ZAR' })
Expected: visible
Timeout: 15000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 15000ms
  - waiting for getByRole('row').filter({ hasText: 'Financial wallet' }).filter({ hasText: 'ZAR' })

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
  1   | /**
  2   |  * Money flow: maker-checker on funding a user wallet (Epic 18).
  3   |  *
  4   |  * Admin "fund a user" is four-eyes — it DEBITs the operator cash float and
  5   |  * CREDITs a user's wallet, so it must be proposed by one admin and approved by
  6   |  * another before any ledger write.
  7   |  *
  8   |  * 1. As the MAKER (admin-test), open the /system-wallets "Fund user" dialog,
  9   |  *    target the seeded Alice (+27825550001) by phone identifier, and propose a
  10  |  *    distinct ZAR amount → "Proposed for approval" toast.
  11  |  * 2. As the CHECKER (admin-approver — different admin), approve it under
  12  |  *    Approvals → Transactions (Approve + Confirm → APPLIED).
  13  |  * 3. Assert the effect on Alice's user-detail page: her ZAR wallet available
  14  |  *    balance rose by exactly the funded amount.
  15  |  *
  16  |  * The amount is randomised and small (sub-1000, well under any wallet ceiling)
  17  |  * so the money-operation summary is individually findable and re-runs simply
  18  |  * stack more funds without colliding. The seed pre-funds the operator float, so
  19  |  * the fund can actually apply.
  20  |  */
  21  | import { test, expect, type Page } from "@playwright/test";
  22  | 
  23  | import { STORAGE_STATE } from "../playwright.config";
  24  | 
  25  | test.use({ storageState: STORAGE_STATE.maker });
  26  | 
  27  | /** Alice, seeded in the default tenant with a single ZAR wallet (make seed). */
  28  | const ALICE_PHONE = "+27825550001";
  29  | const ALICE_LOOKUP = `/users?type=phone&value=${encodeURIComponent(ALICE_PHONE)}`;
  30  | 
  31  | /** A distinct sub-1000 amount ("NNN.NN") — no thousands separator to escape. */
  32  | function uniqueAmount(): string {
  33  |   const base = 100 + Math.floor(Math.random() * 800);
  34  |   const cents = String(Math.floor(Math.random() * 100)).padStart(2, "0");
  35  |   return `${base}.${cents}`;
  36  | }
  37  | 
  38  | /** Read Alice's ZAR financial-wallet AVAILABLE balance as a number. */
  39  | async function readAliceZarAvailable(page: Page): Promise<number> {
  40  |   await page.goto(ALICE_LOOKUP);
  41  |   // Alice holds both a ZAR and an INR financial wallet — scope to ZAR.
  42  |   const row = page
  43  |     .getByRole("row")
  44  |     .filter({ hasText: "Financial wallet" })
  45  |     .filter({ hasText: "ZAR" });
> 46  |   await expect(row).toBeVisible();
      |                     ^ Error: expect(locator).toBeVisible() failed
  47  |   // The Available cell is the row's only font-semibold cell.
  48  |   const text = await row.locator("td.font-semibold").innerText();
  49  |   return parseFloat(text.replace(/[^0-9.]/g, ""));
  50  | }
  51  | 
  52  | test("maker proposes funding Alice; checker approves and her balance rises", async ({
  53  |   page,
  54  |   browser,
  55  | }) => {
  56  |   const amount = uniqueAmount();
  57  | 
  58  |   const balanceBefore = await readAliceZarAvailable(page);
  59  | 
  60  |   // ---- Maker: propose the fund -------------------------------------------
  61  |   await page.goto("/system-wallets");
  62  |   await expect(page.getByRole("heading", { name: "System wallets" })).toBeVisible();
  63  |   await page.getByRole("button", { name: "Fund user" }).click();
  64  | 
  65  |   const dialog = page.getByRole("dialog");
  66  |   await expect(dialog.getByText("Fund a user wallet")).toBeVisible();
  67  |   // Identifier type defaults to Phone; the value input carries the phone
  68  |   // placeholder. Currency defaults to ZAR.
  69  |   await dialog.getByPlaceholder("+27 82 555 0001").fill(ALICE_PHONE);
  70  |   await dialog.getByLabel("Amount", { exact: true }).fill(amount);
  71  |   await dialog.getByLabel(/Reason/).fill(`E2E fund Alice ${amount}`);
  72  |   await dialog.getByRole("button", { name: "Fund user" }).click();
  73  | 
  74  |   await expect(page.getByText(/proposed for approval/i)).toBeVisible();
  75  | 
  76  |   // ---- Checker: approve under Transactions -------------------------------
  77  |   const checkerContext = await browser.newContext({
  78  |     storageState: STORAGE_STATE.checker,
  79  |   });
  80  |   const checkerPage = await checkerContext.newPage();
  81  |   try {
  82  |     // Status values are the UPPERCASE StatusKeys (lib/approvals-filter.ts);
  83  |     // anything else silently falls back to the default PENDING filter.
  84  |     await checkerPage.goto("/approvals?tab=transactions&status=PENDING");
  85  |     await expect(
  86  |       checkerPage.getByRole("heading", { name: "Approvals" }),
  87  |     ).toBeVisible();
  88  | 
  89  |     // Summary reads "Fund Alice Mokoena with ZAR NNN.NN" — match by the unique amount.
  90  |     const opRow = checkerPage.getByRole("row").filter({ hasText: amount });
  91  |     await expect(opRow).toBeVisible();
  92  |     await opRow.getByRole("button", { name: "View" }).click();
  93  | 
  94  |     const drawer = checkerPage.getByRole("dialog");
  95  |     await drawer.getByRole("button", { name: "Approve" }).click();
  96  |     await drawer.getByRole("button", { name: "Confirm approve" }).click();
  97  | 
  98  |     await expect(checkerPage.getByText(/operation approved/i)).toBeVisible();
  99  |     // Approving revalidates + closes the drawer; the APPLIED effect is verified
  100 |     // below on Alice's balance. Confirm it also left the Pending queue.
  101 |     await checkerPage.goto("/approvals?tab=transactions&status=APPLIED");
  102 |     await expect(
  103 |       checkerPage.getByRole("row").filter({ hasText: amount }),
  104 |     ).toBeVisible();
  105 |   } finally {
  106 |     await checkerContext.close();
  107 |   }
  108 | 
  109 |   // ---- Effect: Alice's ZAR available balance rose by the funded amount ---
  110 |   await expect
  111 |     .poll(async () => readAliceZarAvailable(page), { timeout: 15_000 })
  112 |     .toBeGreaterThan(balanceBefore);
  113 | 
  114 |   const balanceAfter = await readAliceZarAvailable(page);
  115 |   expect(Math.abs(balanceAfter - (balanceBefore + Number(amount)))).toBeLessThan(0.01);
  116 | });
  117 | 
```