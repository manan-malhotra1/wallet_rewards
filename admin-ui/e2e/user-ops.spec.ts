/**
 * User maker-checker on editing a seeded user (Epic 3).
 *
 * Admin edits to a user are four-eyes — the Edit drawer PROPOSES an
 * `update_user` operation rather than mutating the user directly.
 *
 * 1. As the MAKER (admin-test), on Alice's user-detail page open the Edit
 *    drawer and change her first + last name to fresh values, then Submit for
 *    approval → "Edit request submitted" toast. Alice's record is unchanged.
 * 2. As the CHECKER (admin-approver — a different admin), approve it under
 *    Approvals → Users (Approve + Confirm → APPLIED).
 * 3. Assert the effect: Alice's user-detail hero now shows the new name.
 *
 * Names are suffixed with a per-run token so the effect assertion is
 * unambiguous. The run drives its own proposal to APPLIED, so it leaves no open
 * update request behind to block a re-run's Edit drawer.
 */
import { test, expect } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

const ALICE_PHONE = "+27825550001";
const ALICE_LOOKUP = `/users?type=phone&value=${encodeURIComponent(ALICE_PHONE)}`;

test("maker proposes an edit to Alice's name; checker approves and it applies", async ({
  page,
  browser,
}) => {
  const token = Date.now().toString().slice(-6);
  const newFirst = `Alicia${token}`;
  const newLast = `Mokoena${token}`;

  // ---- Maker: propose the edit -------------------------------------------
  await page.goto(ALICE_LOOKUP);
  await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
  await page.getByRole("button", { name: "Edit" }).click();

  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText("Edit user")).toBeVisible();

  // Self-heal: an aborted earlier run can leave a PENDING edit, which blocks a
  // new proposal (the drawer shows the open request instead of the form). The
  // maker withdraws it under Approvals → Users, then reopens the edit drawer.
  if (await drawer.getByText("An edit is already awaiting approval").isVisible()) {
    await page.goto("/approvals?tab=users&status=PENDING");
    const staleRow = page.getByRole("row").filter({ hasText: "Edit user" }).first();
    await staleRow.getByRole("button", { name: "View" }).click();
    const staleDrawer = page.getByRole("dialog");
    await staleDrawer.getByRole("button", { name: "Withdraw", exact: true }).click();
    await staleDrawer.getByRole("button", { name: "Confirm withdraw" }).click();
    await expect(page.getByText(/withdrawn/i).first()).toBeVisible();
    await page.goto(ALICE_LOOKUP);
    await page.getByRole("button", { name: "Edit" }).click();
    await expect(drawer.getByText("Edit user")).toBeVisible();
  }

  await drawer.getByLabel("First name").fill(newFirst);
  await drawer.getByLabel("Last name").fill(newLast);
  await drawer.getByRole("button", { name: "Submit for approval" }).click();

  await expect(page.getByText(/edit request submitted/i)).toBeVisible();

  // ---- Checker: approve under Users --------------------------------------
  const checkerContext = await browser.newContext({
    storageState: STORAGE_STATE.checker,
  });
  const checkerPage = await checkerContext.newPage();
  try {
    // Status values are the UPPERCASE StatusKeys (lib/approvals-filter.ts).
    await checkerPage.goto("/approvals?tab=users&status=PENDING");
    await expect(
      checkerPage.getByRole("heading", { name: "Approvals" }),
    ).toBeVisible();

    // Open the newest pending edit's detail drawer. Scope View to the ROW —
    // a page-level name match would also hit the toolbar's disabled
    // "+ Save as view" button (role-name matching is substring).
    await checkerPage
      .getByRole("row")
      .filter({ hasText: "Edit user" })
      .first()
      .getByRole("button", { name: "View" })
      .click();

    const checkerDrawer = checkerPage.getByRole("dialog");
    await checkerDrawer.getByRole("button", { name: "Approve" }).click();
    await checkerDrawer.getByRole("button", { name: "Confirm approve" }).click();

    await expect(checkerPage.getByText(/operation approved/i)).toBeVisible();
    // Approving revalidates + closes the drawer; the APPLIED effect is verified
    // below on Alice's detail hero.
  } finally {
    await checkerContext.close();
  }

  // ---- Effect: Alice's detail hero shows the new name --------------------
  await expect
    .poll(
      async () => {
        await page.goto(ALICE_LOOKUP);
        return page.getByText(`${newFirst} ${newLast}`).count();
      },
      { timeout: 15_000 },
    )
    .toBeGreaterThan(0);
});
