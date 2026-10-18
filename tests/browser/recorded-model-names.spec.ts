import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';

test('task displays a verified name with exact identity in details, and preserves unknown IDs', async ({ page }) => {
  const requests: string[] = [];
  const knownId = `sha256:${'b'.repeat(64)}`;
  const base = { stage: 'translate', status: 'succeeded', control_epoch: 0, title: 'Synthetic paper', generation: 1 };
  const jobs = [
    { ...base, id: 'known', actual_model: { kind: 'local', display_name: '已记录的模型名称', model_id: knownId } },
    { ...base, id: 'unknown', actual_model: { kind: 'local', model_id: 'unknown/retained-model' } },
  ];
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.slice(7);
    requests.push(path);
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    return route.fulfill({ json: path === '/jobs' ? { items: jobs } : jobs.find(job => path === `/jobs/${job.id}`) ?? { items: [] } });
  });
  await page.goto('/#/jobs/known');
  await expect(page.locator('.job-entry').filter({ hasText: '已记录的模型名称' })).toBeVisible();
  const record = page.locator('.job-detail .model-record').first();
  await expect(record.locator('strong')).toHaveText('已记录的模型名称');
  await record.locator('summary').click();
  await expect(record).toContainText(knownId);
  await page.goto('/#/jobs/unknown');
  await expect(page.locator('.job-detail .model-record').first().locator('strong')).toHaveText('unknown/retained-model');
  expect(requests.some(path => /settings\/(provider|local-models|parser-models)/.test(path))).toBe(false);
});
