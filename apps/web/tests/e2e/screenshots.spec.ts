import { test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { REVIEWER, resetMock } from "./helpers";

/** Not a real test: regenerates docs/screenshots/*.png.  Run with  SCREENSHOTS=1 npx playwright test screenshots  */
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to regenerate docs/screenshots");

const OUT = resolve(process.cwd(), "../../docs/screenshots");
mkdirSync(OUT, { recursive: true });

async function login(page: Page, token: string) {
  await page.addInitScript((t) => localStorage.setItem("gigbid.token", t), token);
}

async function shoot(page: Page, name: string, fullPage = false) {
  await page.waitForTimeout(500);
  await page.screenshot({ path: resolve(OUT, `${name}.png`), fullPage });
}

test("desktop screens", async ({ page, request }) => {
  await resetMock(request);
  await page.setViewportSize({ width: 1360, height: 880 });
  await page.goto("/sign-in");
  await shoot(page, "desktop-01-sign-in");

  const res = await request.post("/api/auth/login", { data: REVIEWER });
  const { access_token } = (await res.json()) as { access_token: string };
  await login(page, access_token);

  await page.goto("/");
  await page.getByTestId("job-row").first().waitFor();
  await shoot(page, "desktop-02-inbox");

  await page.goto("/jobs/job_1001");
  await page.getByTestId("requirement-matrix").waitFor();
  await page.getByTestId("evidence-chip").first().hover();
  await shoot(page, "desktop-03-job-detail", true);

  await page.goto("/studio/job_1001");
  await page.getByTestId("claim").first().waitFor();
  await page.getByTestId("claim").first().hover();
  await shoot(page, "desktop-04-proposal-studio");

  await page.goto("/studio/job_1002");
  await page.getByTestId("edit-btn").click();
  await page.getByTestId("edit-text").fill((await page.getByTestId("edit-text").inputValue()) + "\n\nP.S. Happy to share the error-analysis notebook.");
  await shoot(page, "desktop-05-edit-with-diff", true);

  await page.goto("/pipeline");
  await page.getByTestId("pipeline-board").waitFor();
  await shoot(page, "desktop-06-pipeline");

  await page.goto("/messages/thr_2");
  await page.getByTestId("suggested-reply").waitFor();
  await shoot(page, "desktop-07-messages", true);

  await page.goto("/runs/run_1001");
  await page.getByTestId("node-approval_gate").waitFor();
  await page.waitForTimeout(800);
  await shoot(page, "desktop-08-run-viewer", true);

  await page.goto("/analytics");
  await page.getByTestId("sample-banner").waitFor();
  await shoot(page, "desktop-09-analytics", true);

  await page.goto("/settings");
  await page.getByTestId("memory-list").waitFor();
  await shoot(page, "desktop-10-settings", true);

  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await page.getByTestId("job-row").first().waitFor();
  await shoot(page, "desktop-11-inbox-dark");

  await request.post("/api/_mock/degrade", { data: { degraded: true } });
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/studio/job_1001");
  await page.getByTestId("degraded-banner").waitFor();
  await shoot(page, "desktop-12-degraded");
  await request.post("/api/_mock/degrade", { data: { degraded: false } });
});

test("mobile screens", async ({ browser, request }) => {
  await resetMock(request);
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  const res = await request.post("/api/auth/login", { data: REVIEWER });
  const { access_token } = (await res.json()) as { access_token: string };

  await page.goto("/sign-in");
  await shoot(page, "mobile-01-sign-in");
  await login(page, access_token);
  await page.goto("/");
  await page.getByTestId("job-row").first().waitFor();
  await shoot(page, "mobile-02-inbox");
  await page.getByTestId("menu-button").click();
  await shoot(page, "mobile-03-menu");
  await page.goto("/studio/job_1001");
  await page.getByTestId("approval-panel").waitFor();
  await shoot(page, "mobile-04-studio", true);
  await page.goto("/pipeline");
  await page.getByTestId("pipeline-board").waitFor();
  await shoot(page, "mobile-05-pipeline");
  await page.goto("/messages/thr_2");
  await page.getByTestId("suggested-reply").waitFor();
  await shoot(page, "mobile-06-messages");
  await ctx.close();
});
