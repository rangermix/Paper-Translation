import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';

async function fixture(page: Page, local = false, parser = 'surya-ocr-2-v1') {
  const writes: string[] = [];
  let failed = false, status: string | undefined = 'ready';
  await page.route('**/api/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') writes.push(path);
    if (failed && ['/settings/parser-models', '/settings/local-models'].includes(path)) return route.fulfill({ status: 503, json: { error: { code: 'UNAVAILABLE', message: 'Synthetic unavailable' } } });
    const values: Record<string, unknown> = {
      '/settings/preferences': { generation: 1, locale: 'zh-Hans', theme: 'light', parser_profile_revision: parser, local_analyst_model_id: 'synthetic/translator@sha256:example', local_analyst_backend: 'llama.cpp' },
      '/settings/provider': { generation: 1, configured: true, has_api_key: false, api_protocol: local ? 'local_translation' : 'responses', provider: local ? 'local' : 'openai', auth_mode: 'none', endpoint: '', model_id: local ? 'synthetic/translator@sha256:example' : 'synthetic-remote', local_backend: 'llama.cpp' },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false },
      '/settings/parser-environment': { online: true, default: 'dmr', options: [{ id: 'dmr', profiles: ['surya-ocr-2-v1', 'chandra-ocr-2-v1'] }] },
      '/settings/parser-models': { models: [{ id: 'surya-ocr-2-v1', label: 'Surya OCR 2', model_id: 'synthetic/parser', description: 'Synthetic catalog description', download_bytes: 1000000, status }] },
      '/settings/local-models': { models: [{ id: 'synthetic-translator', label: '示例翻译模型', model_id: 'synthetic/translator@sha256:example', family: 'example', family_label: '示例', parameter_size: '2B', bits: 4, quantization: 'Q4', format: 'gguf', runtime: 'llama.cpp', repo: 'synthetic/translator', download_bytes: 1000000, status }] },
      '/documents': { items: [], total: 0 },
    };
    return route.fulfill({ json: values[path] ?? {}, headers: { ETag: '"1"' } });
  });
  await page.goto('/#/settings');
  await expect(page.getByRole('heading', { name: 'AI 服务', exact: true })).toBeVisible();
  return { writes, fail: () => { failed = true; }, omitStatus: () => { status = undefined; } };
}

test('parser identity, purpose and readiness come from catalog without preparing models', async ({ page }) => {
  const state = await fixture(page);
  const details = page.locator('#settings-parser .model-choice-details');
  await details.locator('summary').click();
  await expect(details).toContainText('识别 PDF 页面的原文');
  await expect(details).toContainText('synthetic/parser');
  await expect(details).toContainText('准备状态：已准备');
  await expect(details).toContainText('当前设备的速度与质量对比：未提供');
  state.fail();
  await expect(details).toContainText('准备状态：状态读取失败', { timeout: 10000 });
  await expect(details).not.toContainText('准备状态：已准备');
  expect(state.writes).toEqual([]);
});

test('missing readiness and retired choices never become a ready model or automatic replacement', async ({ page }) => {
  const state = await fixture(page, false, 'docling-v1');
  const select = page.getByLabel('默认 PDF 解析方案');
  await expect(select).toHaveValue('docling-v1');
  await page.locator('#settings-parser .model-choice-details > summary').click();
  await expect(page.locator('#settings-parser .model-choice-details')).toContainText('历史解析方案已停用');
  state.omitStatus();
  await select.selectOption('surya-ocr-2-v1');
  await expect(page.locator('#settings-parser .model-choice-details')).toContainText('准备状态：状态未提供', { timeout: 10000 });
  expect(state.writes).toEqual([]);
});

test('local models expose a human name, exact identity and unknown performance without automatic requests', async ({ page }) => {
  const state = await fixture(page, true);
  const region = page.getByRole('region', { name: '本地翻译模型', exact: true });
  await expect(region.locator('.model-choice-name')).toHaveText('示例翻译模型');
  await expect(region).toContainText('用途：在当前实例中生成译文');
  await region.getByText('模型 ID 与性能说明', { exact: true }).click();
  await expect(region.locator('.model-choice-details')).toContainText('synthetic/translator@sha256:example');
  await expect(region).toContainText('当前设备的速度与质量对比：未提供');
  state.fail();
  await region.getByRole('button', { name: '刷新模型状态' }).click();
  await expect(region.locator('.local-model-status')).toContainText('状态更新失败');
  await expect(region.locator('.local-model-status')).not.toContainText('已下载');
  expect(state.writes).toEqual([]);
});

test('upload analysis summary exposes identity and never presents a failed refresh as ready', async ({ page }) => {
  const state = await fixture(page);
  await page.goto('/#/upload');
  await page.getByLabel('翻译前准备', { exact: true }).selectOption('local');
  const region = page.getByRole('region', { name: '本地分析模型', exact: true });
  await expect(region.getByRole('status')).toContainText('已下载');
  await region.getByText('模型 ID 与性能说明', { exact: true }).click();
  await expect(region).toContainText('synthetic/translator@sha256:example');
  await expect(region).toContainText('当前设备的速度与质量对比：未提供');
  state.fail();
  await expect(region.getByRole('status')).toContainText('状态更新失败', { timeout: 10000 });
  expect(state.writes).toEqual([]);
});
