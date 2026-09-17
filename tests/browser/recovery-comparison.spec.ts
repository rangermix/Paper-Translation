import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

test('recovery task shows paginated before and after text safely on desktop and mobile', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const job = { id: 'recovery_job', stage: 'recovery', status: 'succeeded', title: 'Paper', generation: 1,
    actual_model: { kind: 'none' }, config_snapshot: {}, control_epoch: 0 };
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url()), path = url.pathname.slice(7);
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    let json: unknown = { items: [] };
    if (path === '/capabilities') json = { phase: 'M2' };
    if (path === '/settings/preferences') json = { theme: 'light', locale: 'zh-Hans' };
    if (path === '/jobs') json = { items: [job] };
    if (path === '/jobs/recovery_job') json = job;
    if (path === '/jobs/recovery_job/recovery') {
      const offset = Number(url.searchParams.get('offset') || 0);
      json = { available: true, page: 1, action: 'native_page_recovery', result: 'recovered',
        rule_version: 'native-paragraph-recovery-v2', offset, before_count: 1, after_count: 21,
        before: offset ? [] : ['Complete original paragraph <script>window.bad = true</script>'],
        after: offset ? ['Last recovered paragraph.'] : Array.from({ length: 20 }, (_, i) => `Recovered paragraph ${i + 1}.`),
        next_offset: offset ? null : 20, original_url: '/original.png' };
    }
    return route.fulfill({ json });
  });
  await page.goto('/#/jobs/recovery_job');
  await expect(page).toHaveTitle(/对照文库/);
  const comparison = page.getByRole('region', { name: '恢复前后对照' });
  await expect(comparison.getByRole('heading', { name: '恢复前 · 1 段' })).toBeVisible();
  await expect(comparison.getByText('Complete original paragraph <script>window.bad = true</script>')).toBeVisible();
  await expect(comparison.getByRole('heading', { name: '恢复后 · 21 段' })).toBeVisible();
  expect(await page.evaluate(() => (window as any).bad)).toBeUndefined();
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await comparison.scrollIntoViewIfNeeded();
  await page.screenshot({ path: outputDirectory('recovery-comparison-desktop.png') });
  await comparison.getByRole('button', { name: '下一页对照' }).click();
  await expect(comparison.getByText('Last recovered paragraph.')).toBeVisible();
  await expect(comparison.getByRole('button', { name: '下一页对照' })).toBeDisabled();
  await comparison.getByRole('button', { name: '上一页对照' }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await comparison.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory('recovery-comparison-mobile.png') });
  expect(errors).toEqual([]);
});
