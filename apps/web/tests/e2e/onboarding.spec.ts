import { expect, test } from "@playwright/test";
import { resetMock } from "./helpers";

test.beforeEach(async ({ request }) => resetMock(request));

test("new user registers, picks a persona, uploads a portfolio and lands in the inbox", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.test`;
  await page.goto("/");
  await expect(page).toHaveURL(/\/sign-in/);

  await page.getByTestId("tab-register").click();
  await page.getByLabel("Your name").fill("Test Freelancer");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Password").fill("a-long-test-password");
  await page.getByTestId("auth-submit").click();

  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByRole("heading", { name: "Set up your desk" })).toBeVisible();

  await page.getByRole("radio", { name: /Daniel Okoye/ }).check();
  await page.getByTestId("connect-btn").click();
  await expect(page.getByTestId("connect-btn")).toHaveText("Connected");

  await page.getByTestId("portfolio-input").setInputFiles({
    name: "my-cv.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# My CV\nFull-stack engineer, 6 years."),
  });
  await expect(page.getByTestId("upload-ok")).toContainText("my-cv.md");
  await expect(page.getByTestId("portfolio-files")).toContainText("my-cv.md");

  await page.getByLabel("Hourly rate (USD)").fill("70");
  await page.getByLabel("Weekly Connects budget").fill("40");
  await page.getByTestId("finish-onboarding").click();

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { name: /jobs, ranked by fit/ })).toBeVisible();
  await expect(page.getByTestId("job-row").first()).toBeVisible();
});

test("wrong password shows an error and stays on sign-in", async ({ page }) => {
  await page.goto("/sign-in");
  await page.getByLabel("E-mail").fill("nobody@example.test");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByTestId("auth-submit").click();
  await expect(page.getByTestId("auth-error")).toContainText("Incorrect");
  await expect(page).toHaveURL(/sign-in/);
});
