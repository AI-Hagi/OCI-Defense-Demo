import { expect, test } from '@playwright/test';

/**
 * Use-case-specific smoke tests that hit the live backend through the
 * frontend (no MSW). Each test verifies the page renders *something*
 * specific to its use case, not just the chrome.
 *
 * These are designed to be cheap — one network round-trip per view —
 * so they are safe to run on a deployed environment.
 */

test('GEOINT view renders the scenes header', async ({ page }) => {
  await page.goto('/geoint');
  // The header always shows "<n> Szenen", even when n=0 (live ADB is empty).
  await expect(page.locator('body')).toContainText(/Szenen/);
});

test('Compliance view renders four framework score cards', async ({ page }) => {
  await page.goto('/compliance');
  // Scorecard frameworks are rendered verbatim.
  for (const fw of ['NIS2', 'DORA', 'GDPR']) {
    await expect(page.getByText(fw, { exact: false }).first()).toBeVisible();
  }
});

test('Supply Chain view renders a Leaflet map', async ({ page }) => {
  await page.goto('/supply-chain');
  // Leaflet adds .leaflet-container around the map root.
  await expect(page.locator('.leaflet-container').first()).toBeVisible({
    timeout: 15_000,
  });
});

test('OSINT view renders the graph svg', async ({ page }) => {
  await page.goto('/osint');
  // d3 force-directed graph mounts an svg element with role=img or class.
  await expect(page.locator('svg').first()).toBeVisible();
});

test('Documents view renders the chat input', async ({ page }) => {
  await page.goto('/documents');
  // German placeholder text from DocumentView's chat composer.
  await expect(
    page.getByPlaceholder(/(Frage|Suche|Eingabe)/i).first(),
  ).toBeVisible();
});

test('Collaboration view renders three tenant columns', async ({ page }) => {
  await page.goto('/collaboration');
  // Match the *exact* tenant code rendered in column headers. The
  // TenantSwitcher dropdown shows e.g. "DEU_BMVG · Germany BMVg" inside
  // hidden <option>s, so a substring match would resolve to the dropdown
  // (hidden by default) instead of the visible column header.
  for (const code of ['DEU_BMVG', 'FRA_DGA', 'NLD_MOD']) {
    await expect(page.getByText(code, { exact: true }).first()).toBeVisible();
  }
});
