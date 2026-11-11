import { expect, test } from "@playwright/test";
import { loginAsReviewer, resetMock } from "./helpers";

test.beforeEach(async ({ page, request }) => {
  await resetMock(request);
  await loginAsReviewer(page, request);
});

test("analysis streams node by node, pauses on an interrupt and links to the trace", async ({ page }) => {
  await page.goto("/jobs/job_1007");
  await expect(page.getByTestId("not-analyzed")).toBeVisible();
  await page.getByTestId("run-analysis").click();
  await expect(page).toHaveURL(/\/runs\/run_/);

  // incremental: an early node finishes while the approval gate has not been reached
  await expect(page.getByTestId("node-job_analyst")).toHaveAttribute("data-status", "done");
  await expect(page.getByTestId("node-approval_gate")).not.toHaveAttribute("data-status", "interrupted");
  await expect(page.getByTestId("run-status")).toContainText("Running");

  await expect(page.getByTestId("node-writer")).toHaveAttribute("data-status", "done");
  await expect(page.getByTestId("writer-tokens")).toContainText("Hi,");
  await expect(page.getByTestId("node-approval_gate")).toHaveAttribute("data-status", "interrupted", { timeout: 15_000 });
  await expect(page.getByTestId("run-status")).toContainText("Awaiting your approval");
  await expect(page.getByTestId("interrupt-card")).toBeVisible();

  await expect(page.getByTestId("trace-link")).toHaveAttribute("href", /trace/);
  await page.getByRole("button", { name: "Show spans" }).click();
  await expect(page.getByTestId("trace-spans")).toContainText("portfolio.search_evidence");

  // the pending approval now exists on the server
  await page.getByTestId("review-approval").click();
  await expect(page.getByTestId("approval-panel")).toBeVisible();
});

test("a skipped scam run replays instantly and explains why", async ({ page }) => {
  await page.goto("/runs/run_1003");
  await expect(page.getByTestId("run-status")).toContainText("Skipped");
  await expect(page.getByText("Scam pattern detected").first()).toBeVisible();
  await expect(page.getByTestId("interrupt-card")).toHaveCount(0);
});

test("run list shows every state including blocked and dead-letter", async ({ page }) => {
  await page.goto("/runs");
  const list = page.getByTestId("run-list");
  for (const label of ["Awaiting your approval", "Skipped", "Submitted", "Blocked", "Dead letter", "Rejected", "Needs attention"]) {
    await expect(list.getByText(label, { exact: true }).first()).toBeVisible();
  }
});
