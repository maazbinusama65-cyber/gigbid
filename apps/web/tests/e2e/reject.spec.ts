import { expect, test } from "@playwright/test";
import { REVIEWER, loginAsReviewer, resetMock } from "./helpers";

test.beforeEach(async ({ page, request }) => {
  await resetMock(request);
  await loginAsReviewer(page, request);
});

test("rejecting requires a reason, records it and sends nothing", async ({ page }) => {
  await page.goto("/studio/job_1002");
  await page.getByTestId("reject-btn").click();

  await page.getByTestId("confirm-reject-btn").click();
  await expect(page.getByTestId("reason-error")).toContainText("Enter a reason");
  await expect(page.getByTestId("approval-panel").getByTestId("approval-status")).toHaveText("pending");

  await page.getByTestId("reject-reason").fill("Tone too formal for this client");
  await page.getByTestId("confirm-reject-btn").click();
  await expect(page.getByTestId("decision-result")).toContainText("Rejected");
  await expect(page.getByTestId("decision-result")).toContainText("Nothing was sent");

  await page.goto("/pipeline");
  await expect(page.getByTestId("col-submitted").locator('[data-job="job_1002"]')).toHaveCount(0);
  await expect(page.getByTestId("col-drafted").locator('[data-job="job_1002"]')).toHaveCount(0);

  await page.goto("/analytics");
  await expect(page.getByTestId("rejection-reasons")).toContainText("Tone too formal for this client");
});

test("the API also refuses a rejection without a reason", async ({ request }) => {
  const login = await request.post("/api/auth/login", { data: REVIEWER });
  const { access_token } = (await login.json()) as { access_token: string };
  const res = await request.post("/api/approvals/appr_1002/decision", {
    headers: { Authorization: `Bearer ${access_token}` },
    data: { action: "reject" },
  });
  expect(res.status()).toBe(422);
});
