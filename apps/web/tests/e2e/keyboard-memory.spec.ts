import { expect, test } from "@playwright/test";
import { loginAsReviewer, resetMock } from "./helpers";

test.beforeEach(async ({ page, request }) => {
  await resetMock(request);
  await loginAsReviewer(page, request);
});

test("skip link is the first tab stop and moves focus to main content", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("job-row").first()).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
});

test("every learned memory item can be deleted", async ({ page }) => {
  await page.goto("/settings");
  const items = page.getByTestId("memory-item");
  await expect(items.first()).toBeVisible();
  const count = await items.count();
  expect(count).toBeGreaterThan(3);
  await page.getByRole("button", { name: /Delete memory: Avoid exclamation marks/ }).click();
  await expect(page.getByTestId("memory-status")).toContainText("Forgotten");
  await expect(items).toHaveCount(count - 1);
  await page.reload();
  await expect(page.getByTestId("memory-item")).toHaveCount(count - 1);
});

test("settings save and connected accounts toggle", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("radio", { name: /Manual/ }).check();
  await page.getByLabel("Weekly Connects budget").fill("30");
  await page.getByTestId("save-settings").click();
  await expect(page.getByTestId("settings-status")).toContainText("Saved");
  await page.reload();
  await expect(page.getByLabel("Weekly Connects budget")).toHaveValue("30");

  const gigsim = page.getByTestId("connections").locator("li", { hasText: "GigSim" });
  await gigsim.getByRole("button", { name: "Connect" }).click();
  await expect(gigsim).toContainText("connected");
});

test("pipeline, messages, analytics and inbox filters render real content", async ({ page }) => {
  await page.goto("/pipeline");
  for (const stage of ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]) {
    await expect(page.getByTestId(`col-${stage}`)).toBeVisible();
    await expect(page.getByTestId(`col-${stage}`).getByTestId("pipeline-card").first()).toBeVisible();
  }
  await page.goto("/analytics");
  await expect(page.getByTestId("sample-banner")).toContainText("Sample data");

  await page.goto("/messages/thr_4");
  await expect(page.getByTestId("safety-note")).toBeVisible();

  await page.goto("/");
  await page.getByLabel("Search").fill("kubernetes");
  await page.getByLabel("Search").press("Enter");
  await expect(page.getByTestId("job-row")).toHaveCount(1);
  await page.getByLabel("Search").fill("zzzz-nothing");
  await page.getByLabel("Search").press("Enter");
  await expect(page.getByTestId("empty-state")).toContainText("No jobs match");
});
