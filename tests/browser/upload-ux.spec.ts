import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const provider = { generation: 1, configured: true, dispatch_configuration_ready: true, provider: 'openai',
  api_protocol: 'responses', auth_mode: 'bearer', endpoint: 'https://example.invalid/v1/responses',
  model_id: 'synthetic-translator', profile_hash: 'a'.repeat(64), cost_control_enabled: true };
const pdf = { name: 'valid.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7 synthetic') };

async function setup(page: Page, uploadReady?: Promise<void>) {
  const writes: { path: string; body: any }[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (!['GET', 'HEAD'].includes(request.method()) && !path.includes('/chunks/')) writes.push({ path, body: request.postDataJSON() });
    if (path === '/uploads') await uploadReady;
    const values: Record<string, unknown> = {
      '/capabilities': { source_mime_types: ['application/pdf'], limits: { max_pdf_bytes: 52428800, max_batch_files: 10, max_pages: 200 } },
      '/settings/preferences': { generation: 1, locale: 'zh-Hans', theme: 'light' },
      '/settings/provider': provider,
      '/settings/dispatch': { generation: 1, dispatch_disabled: false },
      '/uploads': { upload_id: 'upload', status: 'created', chunk_limit: 4096, generation: 1 },
      '/uploads/upload/chunks/0': { upload_id: 'upload', status: 'uploading', generation: 2 },
      '/uploads/upload/finalize': { upload_id: 'upload', status: 'verified', generation: 3 },
      '/imports': { id: 'doc', generation: 1, title: 'Synthetic paper', status: 'parsing' },
    };
    await route.fulfill({ json: values[path] ?? { items: [] }, headers: { ETag: '"1"' } });
  });
  await page.goto('/#/upload');
  await expect(page.getByRole('region', { name: '本次翻译服务', exact: true })).toContainText(provider.model_id);
  return { writes, errors };
}

for (const width of [390, 1440]) test(`upload decision order is visual and keyboard consistent at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
  const { writes, errors } = await setup(page);
  const submit = page.getByRole('button', { name: '上传并翻译', exact: true });
  await expect(submit).toBeDisabled();
  await page.locator('#pdf-files').setInputFiles(pdf);
  const positions = await page.evaluate(() => ['#upload-files-heading', '#upload-options-heading', '#upload-service-heading', '.upload-submit'].map(selector => {
    const node = document.querySelector(selector)!;
    return node.getBoundingClientRect().top + window.scrollY;
  }));
  expect(positions).toEqual([...positions].sort((a, b) => a - b));
  expect(new Set(positions).size).toBe(4);
  await page.getByLabel('处理方式', { exact: true }).focus();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('翻译为', { exact: true })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: '查找语言', exact: true })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('翻译前准备', { exact: true })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.locator('.upload-parser-options > summary')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('region', { name: '本次翻译服务', exact: true }).locator('summary')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('每份文档费用上限（USD）', { exact: true })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(submit).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory(`upload-order-${width}.png`), fullPage: true });
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test('switching to source mode removes translation controls and never submits a saved service or budget', async ({ page }) => {
  const { writes } = await setup(page);
  await page.getByLabel('每份文档费用上限（USD）', { exact: true }).fill('0.25');
  await page.getByLabel('处理方式', { exact: true }).selectOption('source');
  await expect(page.getByLabel('翻译为', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('region', { name: '本次翻译服务', exact: true })).toHaveCount(0);
  await expect(page.getByText('只解析 PDF 并生成原文阅读版，不进行翻译，也不授权向翻译服务发送内容。')).toBeVisible();
  await page.locator('#pdf-files').setInputFiles(pdf);
  await page.getByRole('button', { name: '上传并生成原文阅读版', exact: true }).click();
  await expect.poll(() => writes.find(write => write.path === '/imports')?.body.workflow).toMatchObject({
    translate: false, external_processing_confirmed: false, use_saved_upload_permission: false,
  });
  const workflow = writes.find(write => write.path === '/imports')!.body.workflow;
  expect(workflow).not.toHaveProperty('profile_hash');
  expect(workflow).not.toHaveProperty('budget_micro');
  expect(writes.some(write => write.path.startsWith('/settings'))).toBe(false);
});

test('a mixed batch keeps invalid-file feedback and uploads each valid PDF only once', async ({ page }) => {
  let release!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; });
  const { writes } = await setup(page, waiting);
  await page.locator('#pdf-files').setInputFiles([pdf, { name: 'invalid.txt', mimeType: 'text/plain', buffer: Buffer.from('not PDF') }]);
  await expect(page.getByRole('alert')).toContainText('PDF');
  const submit = page.getByRole('button', { name: '上传并翻译', exact: true });
  await submit.evaluate((node: HTMLButtonElement) => { node.click(); node.click(); });
  await expect.poll(() => writes.filter(write => write.path === '/uploads').length).toBe(1);
  await expect(page.getByRole('button', { name: '正在接收与检查…', exact: true })).toBeDisabled();
  await expect(page.getByLabel('处理方式', { exact: true })).toBeDisabled();
  release();
  await expect.poll(() => writes.filter(write => write.path === '/imports').length).toBe(1);
  await expect(page.getByRole('link', { name: /已入库，后台处理中/ })).toBeVisible();
  expect(writes.filter(write => write.path === '/uploads')).toHaveLength(1);
  await expect(page.getByRole('alert')).toContainText('PDF');
});
