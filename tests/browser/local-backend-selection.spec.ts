import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

// Synthetic compatibility exercises multiple choices; it is not a production GGUF/vLLM entry.
for (const width of [1440, 390]) test(`independent backend restores per model and interface at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  const errors: string[] = []; const writes: any[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const rows = [
    ['hy', 'Hy-MT2', '1.8B', 'gguf'], ['hy', 'Hy-MT2', '1.8B', 'gguf'],
    ['hy', 'Hy-MT2', '7B', 'gguf'], ['milmmt', 'MiLMMT-46', '4B', 'gguf'],
    ['hy', 'Hy-MT2', '1.8B', 'safetensors'],
  ].map(([family, family_label, parameter_size, format], index) => ({
    id: `synthetic-${index}`, model_id: `sha256:${String(index + 1).repeat(64)}`, label: `Synthetic ${index}`,
    family, family_label, parameter_size, format, quantization: 'Q4', bits: 4, runtime: 'llama.cpp',
    default_backend: 'llama.cpp', inference_backends: index === 4 ? ['vllm'] : ['llama.cpp', 'vllm'],
    backend_states: { 'llama.cpp': { status: 'not_downloaded' }, vllm: { status: 'unavailable', code: 'LOCAL_VLLM_UNAVAILABLE' } },
    status: 'not_downloaded', repo: 'synthetic/test-only', revision: 'a'.repeat(40), download_bytes: 1000000000,
  }));
  let profile: any = { generation: 1, configured: false, has_api_key: false, provider: 'openai', api_protocol: 'responses',
    auth_mode: 'bearer', endpoint: '', model_id: '', enabled_pairs: [], cost_control_enabled: false };
  await page.route('**/api/v1/**', route => {
    const request = route.request(); const path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') {
      writes.push({ path, body: request.postDataJSON() });
      if (path === '/settings/provider') profile = { ...profile, ...request.postDataJSON().profile,
        generation: 2, configured: true, dispatch_configuration_ready: true };
    }
    const values: Record<string, unknown> = { '/settings/provider': profile, '/settings/local-models': { models: rows },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false, unknown_attempts: 0, inflight_requests: 0 },
      '/settings/preferences': { generation: 1, locale: 'zh-Hans' }, '/capabilities': { source_mime_types: ['application/pdf'] }, '/jobs': { items: [] } };
    return route.fulfill({ json: values[path] ?? {}, headers: { ETag: `"${profile.generation}"` } });
  });
  await page.goto('/#/settings');
  await expect(page).toHaveURL(/#\/settings$/);
  await expect(page).toHaveTitle(/.+/);
  await expect(page.getByRole('heading', { name: 'AI 服务', exact: true })).toBeVisible();
  const protocol = page.getByLabel('接口类型', { exact: true });
  await page.getByLabel('完整请求 URL', { exact: true }).fill('https://synthetic.invalid/v1/responses');
  await page.getByLabel('模型 ID', { exact: true }).fill('draft-api-model');
  await protocol.selectOption('local_translation');
  const family = page.getByRole('region', { name: '本地翻译模型', exact: true }).getByRole('combobox', { name: '模型系列' });
  const size = page.getByRole('region', { name: '本地翻译模型', exact: true }).getByRole('combobox', { name: '参数规模与量化' });
  const format = page.getByRole('region', { name: '本地翻译模型', exact: true }).getByRole('combobox', { name: '模型格式' });
  const model = page.getByRole('region', { name: '本地翻译模型', exact: true }).getByRole('combobox', { name: '具体模型 ID' });
  const backend = page.getByRole('region', { name: '本地翻译模型', exact: true }).getByRole('combobox', { name: '推理后端' });
  await expect(backend).toBeDisabled();
  await family.selectOption('hy'); await size.selectOption('1.8B · Q4'); await format.selectOption('gguf');
  await model.selectOption(rows[0].model_id); await backend.selectOption('vllm');
  await expect(page.getByRole('region', { name: '本地翻译模型', exact: true }).getByRole('status')).toContainText('vLLM 后端未就绪');
  await expect(page.getByRole('region', { name: '本地翻译模型', exact: true }).getByRole('button', { name: '立即准备模型', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '保存 AI 服务配置', exact: true })).toBeEnabled();
  await model.selectOption(rows[1].model_id); await expect(backend).toHaveValue('llama.cpp');
  await model.selectOption(rows[0].model_id); await expect(backend).toHaveValue('vllm');
  await size.selectOption('7B · Q4'); await format.selectOption('gguf'); await model.selectOption(rows[2].model_id);
  await size.selectOption('1.8B · Q4'); await expect(model).toHaveValue(rows[0].model_id); await expect(backend).toHaveValue('vllm');
  await family.selectOption('milmmt'); await size.selectOption('4B · Q4'); await format.selectOption('gguf'); await model.selectOption(rows[3].model_id);
  await family.selectOption('hy'); await expect(model).toHaveValue(rows[0].model_id); await expect(backend).toHaveValue('vllm');
  await format.selectOption('safetensors'); await model.selectOption(rows[4].model_id);
  await expect(backend).toHaveValue('vllm'); await expect(backend.locator('option')).toHaveCount(2);
  await format.selectOption('gguf'); await expect(model).toHaveValue(rows[0].model_id); await expect(backend).toHaveValue('vllm');
  await protocol.selectOption('responses');
  await expect(page.getByLabel('模型 ID', { exact: true })).toHaveValue('draft-api-model');
  await expect(page.getByLabel('完整请求 URL', { exact: true })).toHaveValue('https://synthetic.invalid/v1/responses');
  await protocol.selectOption('local_translation'); await expect(backend).toHaveValue('vllm');
  expect(writes).toEqual([]);
  await page.getByRole('button', { name: '保存 AI 服务配置', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile).toMatchObject({ model_id: rows[0].model_id, local_backend: 'vllm' });
  await page.reload();
  await expect(model).toHaveValue(rows[0].model_id); await expect(backend).toHaveValue('vllm');
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: outputDirectory(`backend-selector-${width}.png`), fullPage: true });
  expect(errors).toEqual([]);
});

test('incompatible saved backend is visible and never silently replaced', async ({ page }) => {
  const writes: string[] = [];
  const row = { id: 'synthetic-gguf', model_id: `sha256:${'a'.repeat(64)}`, family: 'hy', family_label: 'Hy-MT2',
    parameter_size: '1.8B', quantization: 'Q4', bits: 4, format: 'gguf', runtime: 'llama.cpp',
    inference_backends: ['llama.cpp'], default_backend: 'llama.cpp', repo: 'synthetic/model', revision: 'b'.repeat(40),
    download_bytes: 1000000000, status: 'not_downloaded', backend_states: { 'llama.cpp': { status: 'not_downloaded' } } };
  await page.route('**/api/v1/**', route => {
    const request = route.request(); const path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') writes.push(path);
    const values: Record<string, unknown> = {
      '/settings/provider': { generation: 1, configured: true, has_api_key: false, provider: 'local', api_protocol: 'local_translation',
        auth_mode: 'none', model_id: row.model_id, local_backend: 'vllm', endpoint: 'http://local-translator:8090/v1/completions' },
      '/settings/local-models': { models: [row] }, '/settings/dispatch': { generation: 1, dispatch_disabled: false },
      '/settings/preferences': { generation: 1, locale: 'zh-Hans' }, '/capabilities': { source_mime_types: ['application/pdf'] }, '/jobs': { items: [] } };
    return route.fulfill({ json: values[path] ?? {}, headers: { ETag: '"1"' } });
  });
  await page.goto('/#/settings');
  const backend = page.getByRole('region', { name: '本地翻译模型', exact: true }).getByRole('combobox', { name: '推理后端' });
  await expect(backend).toHaveValue('vllm');
  await expect(backend.locator('option:checked')).toHaveText('已保存后端（当前模型或部署不支持）');
  await expect(page.getByRole('button', { name: '保存 AI 服务配置', exact: true })).toBeDisabled();
  await expect(page.getByRole('region', { name: '本地翻译模型', exact: true }).getByRole('button', { name: '立即准备模型', exact: true })).toBeDisabled();
  await backend.selectOption('llama.cpp');
  await expect(page.getByRole('button', { name: '保存 AI 服务配置', exact: true })).toBeEnabled();
  expect(writes).toEqual([]);
});
