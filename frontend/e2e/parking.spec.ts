import { expect, test } from '@playwright/test';

test('v1 diagnostic card with explicit HTTP fixture: free, occupied, unavailable; controls disabled', async ({ page }) => {
  let occupied = false, unavailable = false;
  await page.route('**/api/v1/diagnostics/legacy', async route => {
    if (unavailable) return route.abort('failed');
    return route.fulfill({ json: { profile: 'hybrid-v1-readonly', selected: true, enabled: true, readOnly: true,
      unitId: 1, protocolVersion: 256, connected: true, quality: 'reported', observedAt: Date.now(), ageMs: 0,
      staleAfterMs: 2000, deviceHealth: 1, physicalSlotId: 1, deviceKnown: true, occupied,
      rawRegisters: [1, 256, 1, Number(occupied), Number(occupied), 1],
      freshnessGuarantee: 'communication-only', message: 'UI test fixture' } });
  });
  await page.goto('http://127.0.0.1:15174');
  await page.getByLabel('Token de acces', { exact: true }).fill(process.env.PARKING_E2E_TOKEN!);
  await page.getByRole('button', { name: 'Conectează API', exact: true }).click();
  const sensor = page.getByRole('region', { name: 'Senzor fizic v1.0' });
  await expect(sensor.getByText('P01 liber (raportat de placă)', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Intrare vehicul', exact: true })).toBeDisabled();
  await expect(page.getByRole('heading', { name: 'Situația parcării' })).toHaveCount(0);
  occupied = true;
  await expect(sensor.getByText('P01 ocupat (raportat de placă)', { exact: true })).toBeVisible();
  unavailable = true;
  await expect(sensor.getByText('P01 necunoscut', { exact: true })).toBeVisible();
});

test('React → HTTP adapter → Vite proxy → FastAPI: enter, pay, exit', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto('http://127.0.0.1:15173');
  await expect(page.getByRole('button', { name: 'Intrare vehicul', exact: true })).toBeDisabled();
  await page.getByLabel('Token de acces', { exact: true }).fill(process.env.PARKING_E2E_TOKEN!);
  await page.getByRole('button', { name: 'Conectează API', exact: true }).click();
  await expect(page.getByText('API conectat · date furnizate de backend')).toBeVisible();
  await expect(page.getByText('Simulare backend', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Intrare vehicul', exact: true }).click();
  await page.getByLabel('Număr de înmatriculare', { exact: true }).fill('B 123 DEM');
  await page.getByRole('button', { name: 'Autorizează intrarea', exact: true }).click();
  const row = page.getByRole('row').filter({ hasText: 'B 123 DEM' });
  await expect(row.getByText('Neplătit', { exact: true })).toBeVisible();
  await row.getByRole('button', { name: 'Plată demo', exact: true }).click();
  await expect(row.getByText('Plătit · demo', { exact: true })).toBeVisible();
  await row.getByRole('button', { name: 'Autorizează ieșirea', exact: true }).click();
  await expect(row).toHaveCount(0);
  await expect(page.getByText('Capacitate disponibilă: 4', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Sistem', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Date persistente' })).toBeDisabled();
  expect(pageErrors).toEqual([]);
});

test('hardware mode uses real backend unknown data and disables simulation controls', async ({ page }) => {
  await page.goto('http://127.0.0.1:15174');
  await page.getByLabel('Token de acces', { exact: true }).fill(process.env.PARKING_E2E_TOKEN!);
  await page.getByRole('button', { name: 'Conectează API', exact: true }).click();
  await expect(page.getByText('Mod hardware', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Intrare vehicul', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Simulare senzori', exact: true })).toBeDisabled();
  await expect(page.getByText('Capacitate disponibilă: necunoscută', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Sistem', exact: true }).click();
  await expect(page.getByRole('switch')).toHaveCount(0);
});

test('lost command response resolves through polling without a second POST or invented ID', async ({ page }) => {
  await page.goto('http://127.0.0.1:15173');
  await page.getByLabel('Token de acces', { exact: true }).fill(process.env.PARKING_E2E_TOKEN!);
  await page.getByRole('button', { name: 'Conectează API', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Intrare vehicul', exact: true })).toBeEnabled();
  const posts: string[] = [];
  await page.route('**/api/v1/commands', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    posts.push(route.request().postDataJSON().commandId);
    await route.fetch(); // The real server has admitted the original request.
    await route.abort('failed'); // Only its response is lost.
  });
  await page.getByRole('button', { name: 'Intrare vehicul', exact: true }).click();
  await page.getByLabel('Număr de înmatriculare', { exact: true }).fill('B 999 DEM');
  await page.getByRole('button', { name: 'Autorizează intrarea', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: 'B 999 DEM' }).getByText('Neplătit', { exact: true })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(posts).toHaveLength(1);
  expect(await page.evaluate(() => sessionStorage.getItem('parking.pending-command.v1'))).toBeNull();
});
