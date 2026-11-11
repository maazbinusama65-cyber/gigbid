import { expect, test } from "@playwright/test";
import { loginAsReviewer, resetMock } from "./helpers";

test.beforeEach(async ({ page, request }) => {
  await resetMock(request);
  await loginAsReviewer(page, request);
});

test("editing a draft shows a diff, then sends the edited text", async ({ page }) => {
  await page.goto("/studio/job_1002");
  await page.getByTestId("edit-btn").click();

  const box = page.getByTestId("edit-text");
  const original = await box.inputValue();
  await expect(page.getByTestId("save-edit-btn")).toBeDisabled(); // nothing changed yet

  await box.fill(`${original}\n\nP.S. I can share the error-analysis notebook before we start.`);
  const diff = page.getByTestId("diff");
  await expect(diff.locator("ins")).toContainText("error-analysis notebook");
  await expect(diff.locator("del")).toHaveCount(0);

  await page.getByTestId("save-edit-btn").click();
  await expect(page.getByTestId("decision-result")).toContainText("Sent");
  await expect(page.getByTestId("approval-panel").getByTestId("approval-status")).toHaveText("edited");
  await expect(page.getByTestId("letter")).toContainText("error-analysis notebook");

  await page.goto("/settings");
  await expect(page.getByTestId("memory-list")).toContainText("Edited a draft before sending");
});
