import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

for (const width of [1440, 390]) test(`local model selection and explicit download at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const errors: string[] = []; const writes: { path: string; body: any }[] = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  const rows = ['Hy-MT2-1.8B Q8', 'MiLMMT-46-4B Q4', 'Hy-MT2-7B Q4', 'MiLMMT-46-12B Q4'].map((label, i) => ({
    id: `model-${i}`, label, model_id: `sha256:${String(i).repeat(64)}`, runtime: 'mlx', bits: i ? 4 : 8,
    repo: 'synthetic/model', revision: 'a'.repeat(40), download_bytes: 2000000000, status: 'not_downloaded' }));
  let profile: any = { generation: 1, configured: false, config_source: 'unconfigured', has_api_key: false,
    provider: 'openai', api_protocol: 'responses', auth_mode: 'bearer', model_id: '', endpoint: '', enabled_pairs: [],
    price: {}, cost_control_enabled: false, max_input_tokens: 32768, max_output_tokens: 8192, max_unit_characters: 2000 };
  await page.route('**/api/v1/**', async route => {
    const r = route.request(); const path = new URL(r.url()).pathname.slice(7);
    if (r.method() !== 'GET') {
      writes.push({ path, body: r.postDataJSON() });
      if (path === '/settings/provider') profile = { ...profile, ...r.postDataJSON().profile, generation: 2, configured: true, dispatch_configuration_ready: true };
      if (path.endsWith('/prepare')) rows[1].status = 'downloading';
    }
    const values: Record<string, unknown> = {
      '/settings/provider': profile, '/settings/local-models': { models: rows },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false, maintenance: false, unknown_attempts: 0, inflight_requests: 0 },
      '/settings/preferences': { generation: 1, locale: 'zh-Hans' }, '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'] }, '/jobs': { items: [] } };
    await route.fulfill({ json: values[path] ?? {}, headers: { ETag: `"${profile.generation}"` } });
  });
  await page.goto('/#/settings');
  await expect(page.getByRole('heading', { name: 'AI 服务', exact: true })).toBeVisible();
  await page.getByLabel('接口类型', { exact: true }).selectOption('local_translation');
  const select = page.getByRole('combobox', { name: '本地翻译模型', exact: true });
  await expect(select.locator('option')).toHaveCount(5);
  await select.selectOption(rows[1].model_id);
  await expect(page.getByText('首次使用时下载 · MLX 4 bit · 下载约 2.0 GB')).toBeVisible();
  expect(writes).toEqual([]);
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '保存 AI 服务配置', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile).toMatchObject({ api_protocol: 'local_translation', provider: 'local', auth_mode: 'none', model_id: rows[1].model_id, semantic_review_enabled: false, cost_control_enabled: false });
  expect(writes[0].body.api_key).toBeUndefined();
  await page.getByRole('button', { name: '立即准备模型', exact: true }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1].path).toBe('/settings/local-models/model-1/prepare');
  await expect(page.getByText('正在下载 · MLX 4 bit · 下载约 2.0 GB')).toBeVisible();
  await expect(page.getByRole('button', { name: '测试本地翻译模型' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: outputDirectory(`local-model-${width}.png`), fullPage: true });
  expect(errors).toEqual([]);
});
