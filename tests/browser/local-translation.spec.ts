import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

for (const width of [1440, 390]) test(`local model selection and explicit download at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const errors: string[] = []; const writes: { path: string; body: any }[] = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  const variants = [
    ['Hy-MT2-1.8B Q8', 'hy', 'Hy-MT2', '1.8B', 'Q8'],
    ['MiLMMT-46-4B Q4', 'milmmt', 'MiLMMT-46', '4B', 'Q4'],
    ['Hy-MT2-7B Q4', 'hy', 'Hy-MT2', '7B', 'Q4'],
    ['MiLMMT-46-12B Q4', 'milmmt', 'MiLMMT-46', '12B', 'Q4'],
  ];
  const rows = variants.map(([label, family, family_label, parameter_size, quantization], i) => ({
    id: `model-${i}`, label, model_id: `sha256:${String(i).repeat(64)}`, family, family_label, parameter_size,
    quantization, format: 'mlx', runtime: 'mlx', bits: i ? 4 : 8,
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
  await page.getByRole('combobox', { name: '模型系列' }).selectOption('milmmt');
  await page.getByRole('combobox', { name: '参数规模与量化' }).selectOption('4B · Q4');
  await page.getByRole('combobox', { name: '模型格式' }).selectOption('mlx');
  const select = page.getByRole('combobox', { name: '具体模型 ID' });
  await expect(select.locator('option')).toHaveCount(2);
  await select.selectOption(rows[1].model_id);
  await expect(page.getByText('首次使用时下载 · MLX Q4 · 下载约 2.0 GB')).toBeVisible();
  await page.getByRole('combobox', { name: '参数规模与量化' }).selectOption('12B · Q4');
  await page.getByRole('combobox', { name: '参数规模与量化' }).selectOption('4B · Q4');
  await expect(select).toHaveValue(rows[1].model_id);
  await page.getByRole('combobox', { name: '模型系列' }).selectOption('hy');
  await page.getByRole('combobox', { name: '模型系列' }).selectOption('milmmt');
  await expect(select).toHaveValue(rows[1].model_id);
  await page.getByLabel('接口类型', { exact: true }).selectOption('responses');
  await page.getByLabel('接口类型', { exact: true }).selectOption('local_translation');
  await expect(select).toHaveValue(rows[1].model_id);
  expect(writes).toEqual([]);
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '保存 AI 服务配置', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile).toMatchObject({ api_protocol: 'local_translation', provider: 'local', auth_mode: 'none', model_id: rows[1].model_id, semantic_review_enabled: false, cost_control_enabled: false });
  expect(writes[0].body.api_key).toBeUndefined();
  await page.getByRole('button', { name: '立即准备模型', exact: true }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1].path).toBe('/settings/local-models/model-1/prepare');
  await expect(page.getByText('正在下载 · MLX Q4 · 下载约 2.0 GB')).toBeVisible();
  await expect(page.getByRole('button', { name: '测试本地翻译模型' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: outputDirectory(`local-model-${width}.png`), fullPage: true });
  expect(errors).toEqual([]);
});

test('format switch restores the exact model', async ({ page }) => {
  const rows = ['mlx', 'gguf'].map((format, index) => ({
    id: `hy-${format}`, label: `Hy-MT2-7B Q4 ${format}`, model_id: `sha256:${String(index + 1).repeat(64)}`,
    family: 'hy', family_label: 'Hy-MT2', parameter_size: '7B', quantization: format === 'gguf' ? 'Q4_K_M' : 'Q4',
    bits: 4, format, runtime: format === 'gguf' ? 'llama.cpp' : 'mlx', repo: `synthetic/${format}`,
    revision: 'a'.repeat(40), download_bytes: 1000000000, status: 'not_downloaded',
  }));
  const profile = { generation: 1, configured: false, has_api_key: false, api_protocol: 'responses',
    provider: 'openai', auth_mode: 'bearer', endpoint: '', model_id: '', enabled_pairs: [] };
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.slice(7);
    const values: Record<string, unknown> = { '/settings/provider': profile, '/settings/local-models': { models: rows },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false }, '/settings/preferences': { generation: 1, locale: 'zh-Hans' },
      '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'] }, '/jobs': { items: [] } };
    return route.fulfill({ json: values[path] ?? {}, headers: { ETag: '"1"' } });
  });
  await page.goto('/#/settings');
  await page.getByLabel('接口类型', { exact: true }).selectOption('local_translation');
  await page.getByRole('combobox', { name: '模型系列' }).selectOption('hy');
  await page.getByRole('combobox', { name: '参数规模与量化' }).selectOption('7B · Q4');
  const format = page.getByRole('combobox', { name: '模型格式' });
  const model = page.getByRole('combobox', { name: '具体模型 ID' });
  await format.selectOption('mlx'); await model.selectOption(rows[0].model_id);
  await format.selectOption('gguf'); await model.selectOption(rows[1].model_id);
  await format.selectOption('mlx');
  await expect(model).toHaveValue(rows[0].model_id);
  await expect(page.getByText(rows[0].model_id, { exact: true })).toBeVisible();
});

test('stopped local service keeps model selection and saving available', async ({ page }) => {
  const errors: string[] = []; const writes: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const row = { id: 'hy-gguf', label: 'Hy-MT2-1.8B Q4_K_M', model_id: `sha256:${'a'.repeat(64)}`,
    family: 'hy', family_label: 'Hy-MT2', parameter_size: '1.8B', quantization: 'Q4_K_M', bits: 4,
    format: 'gguf', runtime: 'llama.cpp', repo: 'tencent/Hy-MT2-1.8B-GGUF',
    revision: 'b'.repeat(40), download_bytes: 1000000000, status: 'unavailable', code: 'LOCAL_MODEL_SERVICE_UNAVAILABLE' };
  let profile: any = { generation: 1, configured: false, has_api_key: false, api_protocol: 'responses',
    provider: 'openai', auth_mode: 'bearer', endpoint: '', model_id: '', enabled_pairs: [] };
  await page.route('**/api/v1/**', route => {
    const request = route.request(); const path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') {
      writes.push(path);
      if (path === '/settings/provider') profile = { ...profile, ...request.postDataJSON().profile,
        generation: 2, configured: true, dispatch_configuration_ready: true };
    }
    const values: Record<string, unknown> = { '/settings/provider': profile,
      '/settings/local-models': { models: [row], code: 'LOCAL_MODEL_SERVICE_UNAVAILABLE' },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false },
      '/settings/preferences': { generation: 1, locale: 'zh-Hans' },
      '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'] }, '/jobs': { items: [] } };
    return route.fulfill({ json: values[path] ?? {}, headers: { ETag: `"${profile.generation}"` } });
  });
  await page.goto('/#/settings');
  await page.getByLabel('接口类型', { exact: true }).selectOption('local_translation');
  await expect(page.getByRole('combobox', { name: '模型系列' }).locator('option')).toHaveCount(2);
  await expect(page.getByText('本地翻译服务未启动或无法连接，仍可选择和保存模型。准备模型和翻译前，请在部署中启用本地翻译服务。')).toBeVisible();
  await page.getByRole('combobox', { name: '模型系列' }).selectOption('hy');
  await page.getByRole('combobox', { name: '参数规模与量化' }).selectOption('1.8B · Q4');
  await page.getByRole('combobox', { name: '模型格式' }).selectOption('gguf');
  await page.getByRole('combobox', { name: '具体模型 ID' }).selectOption(row.model_id);
  await expect(page.getByRole('button', { name: '立即准备模型', exact: true })).toBeDisabled();
  const save = page.getByRole('button', { name: '保存 AI 服务配置', exact: true });
  await expect(save).toBeEnabled();
  expect(writes).toEqual([]);
  await save.click();
  await expect.poll(() => writes).toEqual(['/settings/provider']);
  expect(profile.model_id).toBe(row.model_id);
  expect(errors).toEqual([]);
});
