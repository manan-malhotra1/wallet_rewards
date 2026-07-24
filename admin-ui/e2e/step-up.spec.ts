/**
 * Motivating flow: maker-checker on a step-up PIN policy.
 *
 * 1. As the MAKER (admin-test), edit a step-up policy's threshold on /step-up
 *    and Propose the change → a "pending approval" toast confirms it entered
 *    the config maker-checker pipeline.
 * 2. The proposal appears on /approvals?tab=configuration filtered to the
 *    step-up config type.
 * 3. In a SECOND context as the CHECKER (admin-approver — a DIFFERENT admin, so
 *    self-approval is not in play), open that request and Approve → its status
 *    moves to APPLIED.
 *
 * Requires at least one seeded step-up policy in the active tenant (see
 * scripts/seed.py / make seed). Selectors are a best-guess from the components
 * and may need tuning on the first live run.
 */
import { test, expect } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

test("maker proposes a step-up threshold change; checker approves it", async ({
  page,
  browser,
}) => {
  // ---- Maker: propose an edit ----------------------------------------------
  await page.goto("/step-up");
  await expect(page.getByRole("heading", { name: "Step-up PIN" })).toBeVisible();

  // Open the first policy's Edit dialog (proposes an `update`).
  await page.getByRole("button", { name: "Edit policy" }).first().click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Edit step-up policy")).toBeVisible();

  // Bump the threshold to a fresh value so the proposal is a real diff.
  const newThreshold = String(300 + Math.floor(Math.random() * 500));
  await dialog.getByLabel("Threshold").fill(newThreshold);
  await dialog.getByRole("button", { name: "Propose change" }).click();

  // Toast title is "Change proposed — pending approval".
  await expect(page.getByText(/pending approval/i)).toBeVisible();

  // ---- Proposal is visible in the Configuration approvals queue ------------
  await page.goto("/approvals?tab=configuration&status=pending&config_type=step_up");
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
  // At least one config-type "Step-up PIN" badge in the queue table.
  await expect(page.getByText("Step-up PIN").first()).toBeVisible();

  // ---- Checker: a different admin approves ---------------------------------
  const checkerContext = await browser.newContext({
    storageState: STORAGE_STATE.checker,
  });
  const checkerPage = await checkerContext.newPage();
  try {
    await checkerPage.goto(
      "/approvals?tab=configuration&status=pending&config_type=step_up",
    );
    // Open the first pending request's detail drawer.
    await checkerPage.getByRole("button", { name: "View" }).first().click();

    const drawer = checkerPage.getByRole("dialog");
    await expect(drawer.getByRole("button", { name: "Approve" })).toBeVisible();
    await drawer.getByRole("button", { name: "Approve" }).click();

    // Approve confirmation toast + the status pill flips to APPLIED.
    await expect(checkerPage.getByText(/request approved/i)).toBeVisible();
    await expect(drawer.getByText(/applied/i)).toBeVisible();
  } finally {
    await checkerContext.close();
  }
});
