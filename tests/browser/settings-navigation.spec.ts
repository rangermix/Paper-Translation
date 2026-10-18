import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

async function fixture(page: Page, conflictSecond = false) {
  let preferences = { generation: 7, locale: 'zh-Hans', theme: 'light', parser_profile_revision: 'surya-ocr-2-v1', parser_timeout_seconds: 7200,
    resources: { max_ram_percent: 80, max_vram_percent: 80, master_concurrency: 2, subjob_concurrency: 1, auto_concurrency: true } };
  let provider = { generation: 3, configured: true, dispatch_configuration_ready: true, config_source: 'managed', has_api_key: false,
    provider: 'openai', api_protocol: 'responses', auth_mode: 'none', endpoint: 'https://synthetic.invalid/v1/responses', model_id: 'synthetic-model',
    cost_control_enabled: false, profile_hash: 'a'.repeat(64) };
  const writes: { path: string; etag?: string; body: any }[] = [], errors: string[] = [];
  let preferenceWrites = 0, providerReads = 0;
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') {
      writes.push({ path, etag: request.headers()['if-match'], body: request.postDataJSON() });
      if (path === '/settings/preferences') {
        preferenceWrites++;
        expect(request.headers()['if-match']).toBe(`"${preferences.generation}"`);
        if (conflictSecond && preferenceWrites === 2) {
          preferences = { ...preferences, generation: preferences.generation + 1 };
          return route.fulfill({ status: 412, json: { error: { code: 'PRECONDITION_FAILED', message: 'Synthetic settings conflict' } } });
        }
        preferences = { ...preferences, ...request.postDataJSON(), generation: preferences.generation + 1 };
        return route.fulfill({ json: preferences, headers: { ETag: `"${preferences.generation}"` } });
      }
      if (path === '/settings/provider') {
        expect(request.headers()['if-match']).toBe(`"${provider.generation}"`);
        provider = { ...provider, ...request.postDataJSON().profile, generation: provider.generation + 1 };
        return route.fulfill({ json: provider, headers: { ETag: `"${provider.generation}"` } });
      }
      throw new Error(`Unexpected mutation ${path}`);
    }
    if (path === '/settings/provider') providerReads++;
    const values: Record<string, unknown> = {
      '/settings/preferences': preferences, '/settings/provider': provider,
      '/settings/dispatch': { generation: 1, dispatch_disabled: false },
      '/settings/resources': { ram_total_bytes: null, ram_used_bytes: null, vram_total_bytes: null, vram_used_bytes: null,
        effective_master_concurrency: 2, effective_subjob_concurrency: 1, active_master_jobs: 0, active_subjobs: 0, waiting_jobs: [], model_references: [] },
      '/settings/parser-environment': { online: true, default: 'dmr', system: 'Linux', architecture: 'amd64', cpu_count: 4,
        options: [{ id: 'dmr', profiles: ['surya-ocr-2-v1', 'chandra-ocr-2-v1'] }] },
      '/settings/parser-models': { models: [{ id: 'surya-ocr-2-v1', status: 'not_downloaded', download_bytes: 1000000000 }] },
      '/settings/local-models': { models: [] }, '/documents': { items: [], total: 0 },
    };
    return route.fulfill({ json: values[path] ?? { items: [] }, headers: { ETag: `"${path === '/settings/provider' ? provider.generation : preferences.generation}"` } });
  });
  await page.goto('/#/settings');
  await expect(page.getByRole('button', { name: '保存 AI 服务配置', exact: true })).toBeVisible();
  return { writes, errors, providerReads: () => providerReads };
}

for (const width of [390, 1440]) test(`settings categories preserve input and expose scope without automatic work at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const { writes, errors } = await fixture(page);
  const navigation = page.getByRole('navigation', { name: '设置分区' });
  await expect(navigation).toBeInViewport();
  await expect(page.getByText('已配置 · 未测试', { exact: true })).toBeVisible();
  await expect(page.locator('.settings-resource-details')).not.toHaveAttribute('open');
  await navigation.getByRole('button', { name: 'PDF 解析', exact: true }).click();
  await expect(page.locator('#settings-parser')).toBeFocused();
  await page.getByLabel('解析超时（分钟）').fill('90');
  await navigation.getByRole('button', { name: '阅读偏好', exact: true }).click();
  await page.getByLabel('管理界面主题').selectOption('dark');
  await expect(page.locator('.settings-draft-summary')).toContainText('PDF 解析');
  await expect(page.locator('.settings-draft-summary')).toContainText('阅读偏好');
  await navigation.getByRole('button', { name: 'PDF 解析', exact: true }).click();
  await expect(page.getByLabel('解析超时（分钟）')).toHaveValue('90');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await navigation.getByRole('button', { name: '高级与运行状态', exact: true }).click();
  await page.locator('.settings-resource-details > summary').click();
  await expect(page.getByText('容量暂不可用')).toHaveCount(2);
  await expect(page.locator('#settings-advanced')).toContainText('可能影响已排队任务');
  await expect(page.locator('#settings-reading')).toContainText('界面主题保存后立即应用');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: outputDirectory(`settings-categories-${width}.png`), fullPage: true });
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

test('save before leaving serializes distinct preference sections with fresh ETags', async ({ page }) => {
  const { writes, errors } = await fixture(page);
  await page.getByLabel('解析超时（分钟）').fill('90');
  await page.getByLabel('管理界面主题').selectOption('dark');
  await page.getByRole('link', { name: '文档库', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '有未保存的设置' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: '继续编辑' }).click();
  await expect(page.getByLabel('解析超时（分钟）')).toHaveValue('90');
  await expect(page.getByLabel('管理界面主题')).toHaveValue('dark');
  await page.getByRole('link', { name: '文档库', exact: true }).click();
  await dialog.getByRole('button', { name: '保存后离开' }).click();
  await expect(page).toHaveURL(/#\/library$/);
  expect(writes).toEqual([
    { path: '/settings/preferences', etag: '"7"', body: { parser_profile_revision: 'surya-ocr-2-v1', parser_timeout_seconds: 5400 } },
    { path: '/settings/preferences', etag: '"8"', body: { locale: 'zh-Hans', theme: 'dark' } },
  ]);
  expect(errors).toEqual([]);
});

test('partial saving preserves the conflicted section and stops navigation', async ({ page }) => {
  const { writes, errors } = await fixture(page, true);
  await page.getByLabel('解析超时（分钟）').fill('90');
  await page.getByLabel('管理界面主题').selectOption('dark');
  await page.getByRole('link', { name: '文档库', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '有未保存的设置' });
  await dialog.getByRole('button', { name: '保存后离开' }).click();
  await expect(dialog).toContainText('阅读偏好尚未保存');
  await expect(page).toHaveURL(/#\/settings$/);
  await dialog.getByRole('button', { name: '继续编辑' }).click();
  await expect(page.getByLabel('管理界面主题')).toHaveValue('dark');
  await expect(page.locator('.settings-draft-summary')).toContainText('阅读偏好');
  await expect(page.locator('.settings-draft-summary')).not.toContainText('PDF 解析');
  expect(writes).toHaveLength(2); expect(errors).toEqual([]);
});

test('refreshing service configuration asks first and preserves public inputs without testing it', async ({ page }) => {
  const { writes, providerReads, errors } = await fixture(page);
  await page.getByLabel('模型 ID', { exact: true }).fill('edited-model');
  const reads = providerReads();
  await page.getByRole('button', { name: '刷新配置', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '刷新设置并保留输入' });
  await dialog.getByRole('button', { name: '继续编辑' }).click();
  expect(providerReads()).toBe(reads);
  await expect(page.getByLabel('模型 ID', { exact: true })).toHaveValue('edited-model');
  await page.getByRole('button', { name: '刷新配置', exact: true }).click();
  await dialog.getByRole('button', { name: '刷新并保留输入' }).click();
  await expect.poll(providerReads).toBe(reads + 1);
  await expect(page.getByLabel('模型 ID', { exact: true })).toHaveValue('edited-model');
  await expect(page.getByRole('region', { name: '配置版本比较' })).toContainText('synthetic-model');
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

test('leaving settings never silently activates or saves another protocol draft', async ({ page }) => {
  const { writes, errors } = await fixture(page);
  await page.getByLabel('模型 ID', { exact: true }).fill('edited-responses-model');
  await page.getByLabel('接口类型', { exact: true }).selectOption('gemini_interactions');
  await page.getByLabel('模型 ID', { exact: true }).fill('edited-gemini-model');
  await page.getByRole('link', { name: '文档库', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '有未保存的设置' });
  await expect(dialog.getByRole('button', { name: '保存后离开' })).toBeDisabled();
  await dialog.getByRole('button', { name: '继续编辑' }).click();
  await expect(page.getByLabel('模型 ID', { exact: true })).toHaveValue('edited-gemini-model');
  await page.getByLabel('接口类型', { exact: true }).selectOption('responses');
  await expect(page.getByLabel('模型 ID', { exact: true })).toHaveValue('edited-responses-model');
  await page.getByRole('link', { name: '文档库', exact: true }).click();
  await dialog.getByRole('button', { name: '放弃修改' }).click();
  await expect(page).toHaveURL(/#\/library$/);
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

test('mobile menu and refresh confirmations keep dirty settings protected after repeated cancellation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { writes, errors } = await fixture(page);
  const model = page.getByLabel('模型 ID', { exact: true });
  await model.fill('edited-and-preserved');
  const refresh = page.getByRole('button', { name: '刷新配置', exact: true });
  await refresh.click();
  await expect(page.getByRole('dialog', { name: '刷新设置并保留输入' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(refresh).toBeFocused();
  await expect(model).toHaveValue('edited-and-preserved');
  await page.getByRole('button', { name: '打开菜单' }).click();
  const menu = page.getByRole('dialog', { name: '主要导航' });
  const link = menu.getByRole('link', { name: '文档库', exact: true });
  await link.click();
  const guard = page.getByRole('dialog', { name: '有未保存的设置' });
  await expect(guard).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(guard).toHaveCount(0);
  await expect(menu).toBeVisible();
  await expect(link).toBeFocused();
  await link.click();
  await guard.getByRole('button', { name: '放弃修改' }).click();
  await expect(page).toHaveURL(/#\/library$/);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

test('a pending save cannot be abandoned or double-submitted through the leave dialog', async ({ page }) => {
  const { writes, errors } = await fixture(page);
  let finish!: () => void;
  const released = new Promise<void>(resolve => { finish = resolve; });
  let started = false;
  await page.route('**/api/v1/settings/preferences', async route => {
    if (route.request().method() !== 'PATCH') return route.fallback();
    started = true;
    await released;
    return route.fallback();
  });
  await page.getByLabel('解析超时（分钟）').fill('90');
  await page.getByRole('button', { name: '保存解析设置', exact: true }).click();
  await expect.poll(() => started).toBe(true);
  await page.getByRole('link', { name: '文档库', exact: true }).click();
  const guard = page.getByRole('dialog', { name: '有未保存的设置' });
  await expect(guard).toBeVisible();
  await expect(guard.getByRole('button', { name: '放弃修改' })).toBeDisabled();
  await expect(guard.getByRole('button', { name: '保存后离开' })).toBeDisabled();
  await page.keyboard.press('Escape');
  await expect(guard).toBeVisible();
  finish();
  await expect(guard.getByRole('button', { name: '继续编辑' })).toBeEnabled();
  await guard.getByRole('button', { name: '保存后离开' }).click();
  await expect(page).toHaveURL(/#\/library$/);
  expect(writes).toHaveLength(1); expect(errors).toEqual([]);
});
