import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const REVIEWER = { email: "reviewer@gigbid.test", password: "e2e-reviewer-pass" };

/** Reset the mock API state (approvals, runs, degraded flag) so specs are independent. */
export async function resetMock(request: APIRequestContext): Promise<void> {
  const res = await request.post("/api/_mock/reset");
  expect(res.ok()).toBeTruthy();
}

export async function setDegraded(request: APIRequestContext, degraded: boolean): Promise<void> {
  const res = await request.post("/api/_mock/degrade", { data: { degraded } });
  expect(res.ok()).toBeTruthy();
}

/** Log in through the API and seed the session token, so specs start on the screen they test. */
export async function loginAsReviewer(page: Page, request: APIRequestContext): Promise<void> {
  const res = await request.post("/api/auth/login", { data: REVIEWER });
  expect(res.ok()).toBeTruthy();
  const { access_token } = (await res.json()) as { access_token: string };
  await page.addInitScript((token) => localStorage.setItem("gigbid.token", token), access_token);
}

export async function noHorizontalOverflow(page: Page): Promise<void> {
  const { overflow, culprits } = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const wide = [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((el) => el.getBoundingClientRect().right > vw + 1 && !el.closest(".board, .table-wrap, .nav"))
      .slice(0, 5)
      .map((el) => `${el.tagName.toLowerCase()}.${el.className}`);
    return { overflow: document.documentElement.scrollWidth - vw, culprits: wide };
  });
  expect(overflow, `page must not scroll sideways; wide elements: ${culprits.join(", ")}`).toBeLessThanOrEqual(1);
}
