import { expect, test } from "@playwright/test";
import { loginAsReviewer, resetMock, setDegraded } from "./helpers";

test.beforeEach(async ({ page, request }) => {
  await resetMock(request);
  await loginAsReviewer(page, request);
});
test.afterEach(async ({ request }) => setDegraded(request, false));

test("marketplace outage shows a banner with retry, queues approvals, and clears on recovery", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.getByTestId("job-row").first()).toBeVisible();
  await expect(page.getByTestId("degraded-banner")).toHaveCount(0);

  await setDegraded(request, true);
  await page.reload();
  const banner = page.getByTestId("degraded-banner");
  await expect(banner).toContainText("Marketplace unavailable");

  await banner.getByRole("button", { name: /Retry/ }).click();
  await expect(banner).toBeVisible(); // still down after a retry

  await page.goto("/studio/job_1001");
  await expect(page.getByText("If you approve, the send is queued")).toBeVisible();
  await page.getByTestId("approve-btn").click();
  await expect(page.getByTestId("decision-result")).toContainText("queued");

  await setDegraded(request, false);
  await page.getByTestId("degraded-banner").getByRole("button", { name: /Retry/ }).click();
  await expect(page.getByTestId("degraded-banner")).toHaveCount(0);
});

test("an unreachable API is reported too", async ({ page }) => {
  await page.route("**/api/health", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByTestId("degraded-banner")).toContainText("Server unreachable");
});
