import { expect, test } from "@playwright/test";
import { loginAsReviewer, noHorizontalOverflow, resetMock } from "./helpers";

test.use({ viewport: { width: 375, height: 812 }, hasTouch: true });

test.beforeEach(async ({ page, request }) => {
  await resetMock(request);
  await loginAsReviewer(page, request);
});

test("phone width: no sideways scroll, menu navigates, studio and messages are usable", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("job-row").first()).toBeVisible();
  await noHorizontalOverflow(page);

  await page.getByTestId("menu-button").click();
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await page.getByRole("link", { name: "Pipeline" }).click();
  await expect(page.getByTestId("pipeline-board")).toBeVisible();
  await noHorizontalOverflow(page); // the board scrolls inside itself, not the page

  await page.goto("/studio/job_1001");
  await expect(page.getByTestId("approval-panel")).toBeVisible();
  await noHorizontalOverflow(page);
  await expect(page.getByTestId("approve-btn")).toBeVisible();

  await page.goto("/messages");
  await expect(page.getByTestId("thread-list")).toBeVisible();
  await noHorizontalOverflow(page);
  await page.getByRole("link", { name: /Mosaic Marketplace/ }).first().click();
  await expect(page.getByTestId("suggested-reply")).toBeVisible();
  await noHorizontalOverflow(page);
});
