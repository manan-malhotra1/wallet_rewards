/**
 * Configurable user types through the maker-checker pipeline (Epic UTYPE).
 *
 * User types stopped being Python constants and became runtime configuration,
 * so the whole point of the feature is that an operator can add one without a
 * deployment. This drives that claim end to end:
 *
 * 1. As the MAKER (admin-test), propose a new Retail type that sits under the
 *    seeded `super_agent` parent → "pending approval". Nothing exists yet.
 * 2. As the CHECKER (admin-approver, a different admin), approve it under
 *    Approvals → Configuration → the "User type" row.
 * 3. Assert the effect: the type is listed under Retail on /user-types, Active.
 *
 * A second test pins the two-level depth cap (spec D7): the parent dropdown
 * offers only top-level types, so a third level cannot be built from the UI
 * even before the service refuses it.
 *
 * Each run invents a distinct label, because a type can be retired but never
 * deleted (D3) — so re-runs must not collide on a code. The code itself is
 * derived from the label and never typed, which is why the dialog has no code
 * field to fill.
 */
import { test, expect } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

/** A label unique to this run, so its derived code cannot collide with a past one. */
function freshLabel(): string {
  const n = Math.floor(Math.random() * 9000) + 1000;
  return `Field agent ${n}`;
}

test("maker proposes a new Retail user type; checker approves and it appears", async ({
  page,
  browser,
}) => {
  const label = freshLabel();

  await page.goto("/user-types");
  await expect(page.getByRole("heading", { name: "User types", level: 1 })).toBeVisible();

  // The three seeded categories are the page's structure — if they are missing
  // the migration did not run, and every assertion below would be misleading.
  for (const category of ["Consumers", "Retail", "Business"]) {
    await expect(page.getByRole("heading", { name: category })).toBeVisible();
  }

  // ---- Maker: propose the type -------------------------------------------
  await page.getByRole("button", { name: "New user type" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("New user type")).toBeVisible();

  // No code field: the code is derived from the label (see the dialog's JSDoc).
  await expect(dialog.getByLabel("Code")).toHaveCount(0);

  await dialog.getByLabel("Label").fill(label);

  // Radix Select, not a native <select> — open it, then pick the option.
  await dialog.getByRole("combobox", { name: "Category" }).click();
  await page.getByRole("option", { name: "Retail" }).click();

  // Retail supports a hierarchy, so the parent choice appears for it.
  await dialog.getByLabel("This type sits under a parent").check();
  await dialog.getByRole("combobox", { name: "Parent type" }).click();
  await page.getByRole("option", { name: "Super agent" }).click();

  await dialog.getByRole("button", { name: "Propose change" }).click();
  await expect(page.getByText(/pending approval/i)).toBeVisible();

  // Not applied yet — a proposal alone must not create the type.
  await page.goto("/user-types");
  await expect(page.getByText(label, { exact: true })).toHaveCount(0);

  // ---- Checker: approve under Configuration → User type ------------------
  const checkerContext = await browser.newContext({
    storageState: STORAGE_STATE.checker,
  });
  const checkerPage = await checkerContext.newPage();
  try {
    // Status params are the UPPERCASE StatusKeys (lib/approvals-filter.ts).
    await checkerPage.goto("/approvals?tab=configuration&status=PENDING");
    await expect(checkerPage.getByRole("heading", { name: "Approvals" })).toBeVisible();

    // Scope View to the ROW: a page-level name match would also hit the
    // toolbar's "+ Save as view" button, since role-name matching is substring.
    await checkerPage
      .getByRole("row")
      .filter({ hasText: "User type" })
      .first()
      .getByRole("button", { name: "View" })
      .click();

    const drawer = checkerPage.getByRole("dialog");
    await drawer.getByRole("button", { name: "Approve" }).click();
    await expect(checkerPage.getByText(/request approved/i)).toBeVisible();
  } finally {
    await checkerContext.close();
  }

  // ---- Effect: the type is now listed, Active, under Retail --------------
  await expect
    .poll(
      async () => {
        await page.goto("/user-types");
        return page.getByRole("row").filter({ hasText: label }).count();
      },
      { timeout: 15_000 },
    )
    .toBeGreaterThan(0);

  const row = page.getByRole("row").filter({ hasText: label });
  await expect(row).toContainText("Active");
  // Created by an operator, so it must not carry the System badge that marks
  // the five immutable platform types.
  await expect(row).not.toContainText("System");
});

test("the parent dropdown offers only top-level types, capping the hierarchy at two levels", async ({
  page,
}) => {
  await page.goto("/user-types");
  await page.getByRole("button", { name: "New user type" }).click();

  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Label").fill(freshLabel());

  // Consumers is flat, so it must not offer a parent at all.
  await dialog.getByRole("combobox", { name: "Category" }).click();
  await page.getByRole("option", { name: "Consumers" }).click();
  await expect(dialog.getByLabel("This type sits under a parent")).toHaveCount(0);

  // Retail is hierarchical: the parent list offers the top-level `super_agent`
  // but NOT `agent`, which is itself a child. Offering a child would let an
  // operator build a third level — the exact thing D7 forbids.
  await dialog.getByRole("combobox", { name: "Category" }).click();
  await page.getByRole("option", { name: "Retail" }).click();
  await dialog.getByLabel("This type sits under a parent").check();
  await dialog.getByRole("combobox", { name: "Parent type" }).click();

  await expect(page.getByRole("option", { name: "Super agent" })).toBeVisible();
  await expect(page.getByRole("option", { name: "Agent", exact: true })).toHaveCount(0);
});
