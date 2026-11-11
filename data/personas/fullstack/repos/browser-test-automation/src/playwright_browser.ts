import { test, expect } from '@playwright/test';

test('checkBrowser', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/login/);
});
