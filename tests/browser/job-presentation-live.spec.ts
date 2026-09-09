import { test, expect } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

test('existing runtime jobs resolve names and remain searchable without mutations', async ({ page }) => {
  test.skip(process.env.LIBRARY_JOBS_LIVE !== '1', 'Read-only check of existing local jobs; enable explicitly.');
  const errors: string[] = []; const writes: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('request', request => { if (!['GET', 'HEAD'].includes(request.method())) writes.push(request.url()); });
  const response = await page.request.get('/api/v1/jobs?limit=30');
  expect(response.ok()).toBe(true);
  const { items } = await response.json();
  expect(items.length).toBeGreaterThan(0);
  for (const job of items) {
    expect(job.title).toBeTruthy();
    if (job.document_id && job.stage !== 'cleanup') {
      const document = await page.request.get(`/api/v1/documents/${encodeURIComponent(job.document_id)}`).then(r => r.json());
      expect(job.title).toBe(document.title);
    }
  }
  await page.goto('/#/jobs');
  await expect(page).toHaveTitle(/对照文库/);
  await expect(page.getByRole('heading', { name: '任务中心', exact: true })).toBeVisible();
  await expect(page.locator('.job-entry')).toHaveCount(items.length);
  await expect(page.locator('.job-entry').first()).toContainText(items[0].title);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await page.screenshot({ path: outputDirectory('jobs-live-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 1232, height: 1024 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory('jobs-live-reference-size.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory('jobs-live-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: '需要处理', exact: true }).click();
  const attention = await page.request.get('/api/v1/jobs?limit=30&group=attention').then(r => r.json());
  await expect(page.locator('.job-entry')).toHaveCount(attention.items.length);
  await page.getByRole('button', { name: '全部任务', exact: true }).click();
  await page.getByRole('searchbox', { name: '搜索任务' }).fill(items[0].title.slice(0, 255));
  const chosen = page.locator(`.job-entry[href="#/jobs/${items[0].id}"]`);
  await expect(chosen).toBeVisible();
  await chosen.click();
  await page.getByText('任务技术信息', { exact: true }).click();
  await expect(page.locator('.job-technical')).toContainText(items[0].id);
  await expect(page.locator('.task-layout > .panel h2').first()).toContainText(items[0].title);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory('jobs-live-detail-mobile.png'), fullPage: true });
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
