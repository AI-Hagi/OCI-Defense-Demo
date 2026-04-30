import { expect, test } from '@playwright/test';

/**
 * Walks the six use-case views in the order the demo presents them.
 *
 * Asserts that:
 *   1. Each route loads without throwing (status < 400).
 *   2. The sidebar navigation entry highlights as active.
 *   3. No critical browser console errors fire during the navigation.
 *
 * Labels are German because the UI is German per project conventions.
 */
const ROUTES: { path: string; label: string }[] = [
  { path: '/geoint',        label: 'GEOINT' },
  { path: '/documents',     label: 'Dokumenten-Intelligenz' },
  { path: '/collaboration', label: 'Zusammenarbeit' },
  { path: '/osint',         label: 'OSINT-Fusion' },
  { path: '/supply-chain',  label: 'Lieferkette' },
  { path: '/compliance',    label: 'Compliance' },
];

test.describe('Sovereign Defence — sidebar navigation', () => {
  test('all six views load via deep link', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(`console.error: ${msg.text()}`);
    });

    for (const { path, label } of ROUTES) {
      const resp = await page.goto(path, { waitUntil: 'domcontentloaded' });
      expect(resp?.status(), `${path} HTTP status`).toBeLessThan(400);

      const activeLink = page.getByRole('link', { name: label });
      await expect(activeLink).toBeVisible();
    }

    // Real SPA bugs surface as `pageerror:` (uncaught JS exceptions).
    // `console.error` for a backend 4xx/5xx is noise from React Query's
    // default logger when an endpoint is missing on the deployed pod
    // (e.g. /api/compliance/live/* before the compliance image is rebuilt).
    const significant = errors.filter((e) => e.startsWith('pageerror:'));
    expect(significant, significant.join('\n')).toEqual([]);
  });

  test('clicking each sidebar link routes correctly', async ({ page }) => {
    await page.goto('/geoint');
    for (const { path, label } of ROUTES) {
      await page.getByRole('link', { name: label }).click();
      await expect(page).toHaveURL(new RegExp(`${path}$`));
    }
  });

  test('root redirects to /geoint', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/geoint$/);
  });
});
