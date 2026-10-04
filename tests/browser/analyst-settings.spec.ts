import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const analysts = [
  { id: 'minicpm5-1b-q4', label: 'MiniCPM5-1B Q4', model_id: `sha256:${'1'.repeat(64)}`,
    family: 'minicpm5', family_label: 'MiniCPM5', parameter_size: '1B', quantization: 'Q4', bits: 4,
    format: 'mlx', runtime: 'mlx', default_backend: 'mlx', inference_backends: ['mlx'],
    repo: 'synthetic/minicpm5-mlx', revision: 'a'.repeat(40), download_bytes: 618659840,
    status: 'not_downloaded', backend_states: { mlx: { status: 'not_downloaded' } } },
  { id: 'minicpm5-1b-q4-k-m-gguf', label: 'MiniCPM5-1B Q4_K_M GGUF', model_id: `sha256:${'2'.repeat(64)}`,
    family: 'minicpm5', family_label: 'MiniCPM5', parameter_size: '1B', quantization: 'Q4_K_M', bits: 4,
    format: 'gguf', runtime: 'llama.cpp', default_backend: 'llama.cpp', inference_backends: ['llama.cpp'],
    repo: 'synthetic/minicpm5-gguf', revision: 'b'.repeat(40), download_bytes: 703000000,
    status: 'not_downloaded', backend_states: { 'llama.cpp': { status: 'not_downloaded' } } },
];
const translator = { ...analysts[1], id: 'translator', model_id: `sha256:${'3'.repeat(64)}`,
  family: 'hy', family_label: 'Hy-MT2', label: 'Independent translator', parameter_size: '1.8B', repo: 'synthetic/translator' };

async function setup(page: Page, conflict = false, unavailable = false) {
  const errors: string[] = [];
  const reads: string[] = [];
  const writes: { path: string; method: string; body: any; etag: string | undefined }[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const rows = analysts.map(row => ({ ...row, ...(unavailable ? { status: 'unavailable', code: 'LOCAL_MODEL_SERVICE_UNAVAILABLE',
    backend_states: { [row.default_backend]: { status: 'unavailable', code: 'LOCAL_MODEL_SERVICE_UNAVAILABLE' } } } : {}) }));
  const provider = { generation: 3, configured: true, has_api_key: false, dispatch_configuration_ready: true,
    provider: 'local', api_protocol: 'local_translation', auth_mode: 'none', endpoint: 'http://local-translator:8090/v1/completions',
    model_id: translator.model_id, local_backend: 'llama.cpp', enabled_pairs: [], cost_control_enabled: false,
    max_input_tokens: 32768, max_output_tokens: 8192, max_unit_characters: 2000 };
  let preferences = { generation: 7, locale: 'zh-Hans', theme: 'light', publish_policy: 'manual_approval',
    parser_profile_revision: 'surya-ocr-2-v1', parser_timeout_seconds: 7200,
    local_analyst_model_id: analysts[0].model_id, local_analyst_backend: 'mlx' };
  let conflictPending = conflict;
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.slice(7);
    if (request.method() === 'GET') reads.push(path + url.search);
    else {
      writes.push({ path: path + url.search, method: request.method(), body: request.postDataJSON(), etag: request.headers()['if-match'] });
      if (path === '/settings/preferences') {
        if (conflictPending) {
          conflictPending = false;
          preferences = { ...preferences, generation: preferences.generation + 1 };
          return route.fulfill({ status: 409, json: { error: { code: 'VERSION_CONFLICT', message: '设置已被其他标签页修改，请刷新后重试。' } } });
        }
        if (request.headers()['if-match'] !== `"${preferences.generation}"`) return route.fulfill({ status: 412, json: { error: { code: 'VERSION_CONFLICT', message: '实例偏好版本不一致。' } } });
        preferences = { ...preferences, ...request.postDataJSON(), generation: preferences.generation + 1 };
      }
    }
    const values: Record<string, unknown> = {
      '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'] },
      '/settings/provider': provider, '/settings/preferences': preferences,
      '/settings/local-models': url.searchParams.get('purpose') === 'analysis'
        ? { models: rows, ...(unavailable ? { code: 'LOCAL_MODEL_SERVICE_UNAVAILABLE' } : {}) } : { models: [translator] },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false, unknown_attempts: 0, inflight_requests: 0 },
      '/settings/parser-environment': { online: true, default: 'dmr', options: [{ id: 'dmr', profiles: ['surya-ocr-2-v1'] }] },
      '/settings/parser-models': { models: [{ id: 'surya-ocr-2-v1', download_bytes: 1200000000, status: 'not_downloaded' }] },
      '/jobs': { items: [] },
    };
    return route.fulfill({ json: values[path] ?? {}, headers: { ETag: `"${path === '/settings/preferences' ? preferences.generation : provider.generation}"` } });
  });
  return { errors, reads, writes, provider };
}

for (const width of [1440, 390]) test(`independent local analyst settings persist without preparing or changing translation at ${width}px`, async ({ page }) => {
  const { errors, reads, writes } = await setup(page);
  await page.setViewportSize({ width, height: 1000 });
  await page.goto('/#/settings');
  await expect(page).toHaveURL(/#\/settings$/);
  await expect(page).toHaveTitle(/对照文库/);
  const panel = page.getByRole('region', { name: '翻译前总结模型', exact: true });
  await expect(panel.getByRole('heading', { name: '翻译前总结模型', exact: true })).toBeVisible();
  const analysis = panel.getByRole('region', { name: '本地分析模型', exact: true });
  const model = analysis.getByRole('combobox', { name: '具体模型 ID', exact: true });
  const backend = analysis.getByRole('combobox', { name: '推理后端', exact: true });
  const translation = page.getByRole('region', { name: '本地翻译模型', exact: true });
  await expect(model).toHaveValue(analysts[0].model_id);
  await expect(backend).toHaveValue('mlx');
  await analysis.getByRole('combobox', { name: '模型格式', exact: true }).selectOption('gguf');
  await model.selectOption(analysts[1].model_id);
  await expect(backend).toHaveValue('llama.cpp');
  await expect(translation.getByRole('combobox', { name: '具体模型 ID', exact: true })).toHaveValue(translator.model_id);
  await expect(translation.getByRole('combobox', { name: '推理后端', exact: true })).toHaveValue('llama.cpp');
  await analysis.getByRole('button', { name: '刷新模型状态', exact: true }).click();
  expect(writes).toEqual([]);
  await panel.getByRole('button', { name: '保存总结模型设置', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({ path: '/settings/preferences', method: 'PATCH', etag: '"7"', body: {
    local_analyst_model_id: analysts[1].model_id, local_analyst_backend: 'llama.cpp',
  } });
  await page.reload();
  await expect(model).toHaveValue(analysts[1].model_id);
  await expect(backend).toHaveValue('llama.cpp');
  await expect(translation.getByRole('combobox', { name: '具体模型 ID', exact: true })).toHaveValue(translator.model_id);
  expect(writes).toHaveLength(1);
  expect(reads).toContain('/settings/local-models?purpose=analysis');
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await panel.screenshot({ path: outputDirectory(`analyst-settings-${width}.png`) });
  await analysis.getByRole('button', { name: '立即准备模型', exact: true }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toEqual({ path: `/settings/local-models/${analysts[1].id}/prepare?backend=llama.cpp`, method: 'POST', body: {}, etag: undefined });
  expect(errors).toEqual([]);
});

test('unavailable analyst service preserves the choice and allows saving without a download', async ({ page }) => {
  const { errors, writes } = await setup(page, false, true);
  await page.goto('/#/settings');
  const panel = page.getByRole('region', { name: '翻译前总结模型', exact: true });
  const analysis = panel.getByRole('region', { name: '本地分析模型', exact: true });
  await expect(analysis.getByRole('combobox', { name: '具体模型 ID', exact: true })).toHaveValue(analysts[0].model_id);
  await expect(analysis.getByRole('status')).toContainText('未就绪');
  await expect(analysis.getByRole('button', { name: '立即准备模型', exact: true })).toBeDisabled();
  await expect(panel.getByRole('button', { name: '保存总结模型设置', exact: true })).toBeEnabled();
  await panel.getByRole('button', { name: '保存总结模型设置', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body).toEqual({ local_analyst_model_id: analysts[0].model_id, local_analyst_backend: 'mlx' });
  expect(writes[0].path).toBe('/settings/preferences');
  expect(errors).toEqual([]);
});

test('conflicting analyst settings require a fresh read and explicit save with the latest generation', async ({ page }) => {
  const { reads, writes } = await setup(page, true);
  await page.goto('/#/settings');
  const panel = page.getByRole('region', { name: '翻译前总结模型', exact: true });
  const analysis = panel.getByRole('region', { name: '本地分析模型', exact: true });
  const model = analysis.getByRole('combobox', { name: '具体模型 ID', exact: true });
  const format = analysis.getByRole('combobox', { name: '模型格式', exact: true });
  const save = panel.getByRole('button', { name: '保存总结模型设置', exact: true });
  await expect(model).toHaveValue(analysts[0].model_id);
  await format.selectOption('gguf');
  await model.selectOption(analysts[1].model_id);
  await save.click();
  await expect(panel.getByRole('alert')).toContainText('设置已被其他标签页修改');
  await expect(save).toBeDisabled();
  await format.selectOption('mlx');
  await expect(model).toHaveValue(analysts[0].model_id);
  await expect(save).toBeDisabled();
  await format.selectOption('gguf');
  await expect(model).toHaveValue(analysts[1].model_id);
  await expect(save).toBeDisabled();
  expect(writes).toHaveLength(1);
  expect(writes[0].etag).toBe('"7"');
  const beforeRefresh = reads.filter(path => path === '/settings/preferences').length;
  await panel.getByRole('button', { name: '重新读取', exact: true }).click();
  await expect(save).toBeEnabled();
  expect(reads.filter(path => path === '/settings/preferences').length).toBeGreaterThan(beforeRefresh);
  await expect(model).toHaveValue(analysts[1].model_id);
  expect(writes).toHaveLength(1);
  await save.click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toMatchObject({ path: '/settings/preferences', etag: '"8"', body: {
    local_analyst_model_id: analysts[1].model_id, local_analyst_backend: 'llama.cpp',
  } });
  await page.reload();
  await expect(model).toHaveValue(analysts[1].model_id);
  await expect(page.getByRole('region', { name: '本地翻译模型', exact: true }).getByRole('combobox', { name: '具体模型 ID', exact: true })).toHaveValue(translator.model_id);
});
