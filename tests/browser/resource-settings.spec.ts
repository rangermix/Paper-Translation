import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const GiB = 1024 ** 3;
const defaults = { max_ram_percent: 80, max_vram_percent: 80, master_concurrency: 2, subjob_concurrency: 1, auto_concurrency: true };
const reference = { kind: 'estimate', weights_bytes: 4.3 * GiB, kv_cache_bytes: GiB, workspace_bytes: GiB,
  ram_bytes: 6.3 * GiB, vram_bytes: 6.3 * GiB, context_tokens: 8192, unified_memory: false };

async function setup(page: Page, { missing = false, conflict = false } = {}) {
  const errors: string[] = [], writes: any[] = [];
  let prefs = { generation: 7, locale: 'zh-Hans', publish_policy: 'manual_approval', theme: 'dark', resources: defaults,
    parser_profile_revision: 'surya-ocr-2-v1', parser_timeout_seconds: 7200 };
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.slice(7);
    if (request.method() !== 'GET') {
      writes.push({ path, body: request.postDataJSON(), etag: request.headers()['if-match'] });
      if (conflict) {
        conflict = false; prefs = { ...prefs, generation: 8 };
        return route.fulfill({ status: 412, json: { error: { code: 'VERSION_CONFLICT', message: '设置已变更，请刷新后重试。' } } });
      }
      expect(path).toBe('/settings/preferences');
      expect(request.headers()['if-match']).toBe(`"${prefs.generation}"`);
      prefs = { ...prefs, ...request.postDataJSON(), generation: prefs.generation + 1 };
    }
    const values: Record<string, any> = {
      '/settings/preferences': prefs,
      '/settings/provider': { configured: false, generation: 1 },
      '/settings/resources': { ram_total_bytes: missing ? null : 64 * GiB, ram_used_bytes: missing ? null : 20 * GiB,
        vram_total_bytes: missing ? null : 24 * GiB, vram_used_bytes: missing ? null : 8 * GiB,
        effective_master_concurrency: 2, effective_subjob_concurrency: 1, active_master_jobs: 1, active_subjobs: 1, worker_limit: 16,
        waiting_jobs: missing ? [{ id: 'waiting', reason: 'RESOURCE_TELEMETRY_UNAVAILABLE' }] : [],
        model_references: [{ id: 'hy-test', label: 'Hy-MT2 7B Q4', memory_reference: reference }] },
      '/settings/local-models': { models: [] },
      '/settings/parser-models': { models: [{ id: 'surya-ocr-2-v1', download_bytes: GiB, status: 'ready', memory_reference: reference }] },
      '/settings/parser-environment': { online: true, default: 'dmr', options: [{ id: 'dmr', profiles: ['surya-ocr-2-v1'] }] },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false }, '/jobs': { items: [] },
    };
    return route.fulfill({ json: values[path] ?? {}, headers: { ETag: `"${prefs.generation}"` } });
  });
  return { errors, writes };
}

for (const width of [1440, 390]) test(`resource limits save and persist without loading models at ${width}px`, async ({ page }) => {
  const { errors, writes } = await setup(page);
  await page.setViewportSize({ width, height: 1000 });
  await page.goto('/#/settings');
  const panel = page.getByRole('region', { name: '资源与并发' });
  await expect(panel.getByLabel('RAM 使用上限（%）', { exact: true })).toHaveValue('80');
  await expect(panel.getByLabel('VRAM 使用上限（%）')).toHaveValue('80');
  await panel.getByLabel('RAM 使用上限（%）', { exact: true }).fill('70');
  await panel.getByLabel('VRAM 使用上限（%）').fill('65');
  await panel.getByLabel('主任务并发上限', { exact: true }).fill('3');
  await panel.getByLabel('每个主任务的子任务并发上限').fill('4');
  await panel.getByRole('checkbox').uncheck();
  await panel.getByRole('button', { name: '保存资源设置' }).click();
  await expect(panel.getByText('资源设置已保存，将用于后续任务调度。')).toBeVisible();
  expect(writes).toEqual([{ path: '/settings/preferences', etag: '"7"', body: { resources: {
    max_ram_percent: 70, max_vram_percent: 65, master_concurrency: 3, subjob_concurrency: 4, auto_concurrency: false } } }]);
  await page.reload();
  await expect(panel.getByLabel('VRAM 使用上限（%）')).toHaveValue('65');
  await panel.getByText('全部模型的内存参考', { exact: true }).click();
  await expect(panel.getByRole('cell', { name: 'Hy-MT2 7B Q4' })).toBeVisible();
  await expect(page.getByLabel('模型内存参考').first()).toContainText('KV 缓存约 1.0 GiB');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: outputDirectory(`resources-${width}.png`), fullPage: true });
  await panel.screenshot({ path: outputDirectory(`resources-panel-${width}.png`) });
  expect(errors).toEqual([]);
});

test('invalid numbers prevent save and absent telemetry is explicit', async ({ page }) => {
  const { writes } = await setup(page, { missing: true });
  await page.goto('/#/settings');
  const panel = page.getByRole('region', { name: '资源与并发' });
  await expect(panel.getByText('容量暂不可用')).toHaveCount(2);
  await expect(panel.getByText('1 个任务等待：等待可用的内存监测。')).toBeVisible();
  for (const value of ['', '101', '7.5']) {
    await panel.getByLabel('RAM 使用上限（%）', { exact: true }).fill(value);
    await expect(panel.getByRole('button', { name: '保存资源设置' })).toBeDisabled();
  }
  expect(writes).toHaveLength(0);
});

test('stale save keeps resource draft and requires refresh', async ({ page }) => {
  const { writes } = await setup(page, { conflict: true });
  await page.goto('/#/settings');
  const panel = page.getByRole('region', { name: '资源与并发' });
  await panel.getByLabel('RAM 使用上限（%）', { exact: true }).fill('73');
  await panel.getByRole('button', { name: '保存资源设置' }).click();
  await expect(panel.getByRole('button', { name: '保存资源设置' })).toBeDisabled();
  await expect(panel.getByLabel('RAM 使用上限（%）', { exact: true })).toHaveValue('73');
  expect(writes).toHaveLength(1);
});
