import { expect, test } from "@playwright/test";
import { loginAsReviewer, resetMock } from "./helpers";

test.beforeEach(async ({ page, request }) => {
  await resetMock(request);
  await loginAsReviewer(page, request);
});

test("approve a proposal: shows dry-run, cost and evidence; decision survives a refresh", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("approval-strip")).toContainText("waiting for your approval");
  await page.getByRole("link", { name: /Build a cited Q&A assistant/ }).click();
  await expect(page.getByTestId("requirement-matrix")).toBeVisible();
  await page.getByTestId("open-studio").click();

  const panel = page.getByTestId("approval-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId("approval-status")).toHaveText("pending");
  await expect(panel.getByTestId("connects-cost")).toHaveText("16");
  await expect(panel.getByTestId("price-rationale")).toBeVisible();
  await expect(panel.getByTestId("critic-block")).toContainText("Critic");
  await expect(panel.getByTestId("compliance-block")).toContainText("Compliance");
  await expect(panel.getByTestId("dry-run")).toContainText("Dry run");
  await expect(panel.getByTestId("dry-run")).toContainText("cover_letter");

  // a pending approval is server state: it is still there after a hard refresh
  await page.reload();
  await expect(page.getByTestId("approval-panel").getByTestId("approval-status")).toHaveText("pending");

  await page.getByTestId("approve-btn").click();
  await expect(page.getByTestId("decision-result")).toContainText("Sent");
  await expect(page.getByTestId("decision-result")).toContainText("16 Connects spent");

  await page.reload();
  await expect(page.getByTestId("approval-panel").getByTestId("approval-status")).toHaveText("approved");

  await page.goto("/pipeline");
  await expect(page.getByTestId("col-submitted").locator('[data-job="job_1001"]')).toBeVisible();
  await expect(page.getByTestId("col-drafted").locator('[data-job="job_1001"]')).toHaveCount(0);
});

test("hovering or focusing a claim shows the evidence behind it", async ({ page }) => {
  await page.goto("/studio/job_1001");
  const claim = page.getByTestId("claim").first();
  await claim.hover();
  const pop = page.getByTestId("evidence-popover");
  await expect(pop).toBeVisible();
  await expect(pop).toContainText("Contract Q&A assistant");
  await page.mouse.move(0, 0);
  await expect(pop).toHaveCount(0);
  await page.getByTestId("claim").nth(1).focus();
  await expect(page.getByTestId("evidence-popover")).toContainText("hybrid_retriever");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("evidence-popover")).toHaveCount(0);
  await expect(page.getByTestId("removed-claim")).toContainText("SOC2");
});

test("regenerating one paragraph changes only that paragraph", async ({ page }) => {
  await page.goto("/studio/job_1001");
  const paras = page.getByTestId("paragraph");
  const before = await paras.allTextContents();
  await page.getByRole("button", { name: "Regenerate paragraph 3" }).click();
  await page.getByTestId("regen-confirm").click();
  await expect(paras.nth(2)).not.toHaveText(before[2] ?? "");
  expect(await paras.nth(0).textContent()).toContain((before[0] ?? "").slice(0, 40));
});
