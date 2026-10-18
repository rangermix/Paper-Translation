import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const storageKey = 'paper-translation.ui-locale.v1';
async function fixture(page: Page) {
  const writes: string[] = [], errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.route('**/api/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') writes.push(path);
    const values: Record<string, unknown> = {
      '/capabilities': { source_mime_types: ['application/pdf'], limits: { max_pdf_bytes: 52428800, max_batch_files: 10, max_pages: 200 } },
      '/settings/preferences': { generation: 7, locale: 'zh-Hans', theme: 'light', parser_profile_revision: 'surya-ocr-2-v1', parser_timeout_seconds: 7200,
        resources: { max_ram_percent: 80, max_vram_percent: 80, master_concurrency: 2, subjob_concurrency: 1, auto_concurrency: true } },
      '/settings/provider': { generation: 3, configured: true, dispatch_configuration_ready: true, config_source: 'managed', has_api_key: false,
        provider: 'openai', api_protocol: 'responses', auth_mode: 'none', endpoint: 'https://synthetic.invalid/v1/responses', model_id: 'synthetic-model', cost_control_enabled: false, profile_hash: 'a'.repeat(64) },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false },
      '/settings/resources': { ram_total_bytes: null, ram_used_bytes: null, vram_total_bytes: null, vram_used_bytes: null,
        effective_master_concurrency: 2, effective_subjob_concurrency: 1, active_master_jobs: 0, active_subjobs: 0, waiting_jobs: [], model_references: [] },
      '/settings/parser-environment': { online: true, default: 'dmr', system: 'Linux', architecture: 'amd64', cpu_count: 4,
        options: [{ id: 'dmr', profiles: ['surya-ocr-2-v1'] }] },
      '/settings/parser-models': { models: [] }, '/settings/local-models': { models: [] },
      '/documents': { items: [{ id: 'doc_i18n', title: '设置', filename: '原始文件.pdf', tags: ['原始标签'], starred: false, lifecycle: 'active', generation: 1, source_asset_id: 'asset', page_count: 2, byte_size: 3000, editions: [] }], total: 1 },
    };
    return route.fulfill({ json: values[path] ?? { items: [] }, headers: { ETag: '"7"' } });
  });
  return { writes, errors };
}

test('switching languages preserves unsaved settings and translation locale without server writes', async ({ page }) => {
  const { writes, errors } = await fixture(page);
  await page.goto('/#/settings');
  await expect(page.getByRole('heading', { name: '设置', exact: true })).toBeVisible();
  await page.locator('#theme').selectOption('dark');
  await page.getByLabel('解析超时（分钟）').fill('90');
  await page.locator('#ui-language').selectOption('en');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
  await expect(page.locator('#theme')).toHaveValue('dark');
  await expect(page.locator('#default-locale')).toHaveValue('zh-Hans');
  await expect(page.locator('.settings-draft-summary')).toBeVisible();
  await page.locator('#ui-language').selectOption('zh-Hant');
  await expect(page.getByRole('heading', { name: '設定', exact: true })).toBeVisible();
  await expect(page.locator('#theme')).toHaveValue('dark');
  await expect(page.locator('#default-locale')).toHaveValue('zh-Hans');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page).toHaveTitle('對照文庫 · 個人 PDF 知識庫');
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

test('choice persists across reload and tabs while document content remains untouched', async ({ page, context }) => {
  const { writes, errors } = await fixture(page);
  await page.goto('/#/library');
  await page.locator('#ui-language').selectOption('en');
  await expect(page.getByRole('heading', { name: 'Library', exact: true })).toBeVisible();
  await expect(page.locator('.doc-card')).toContainText('设置');
  await expect(page.locator('.doc-card')).toContainText('原始标签');
  await page.reload();
  await expect(page.locator('#ui-language')).toHaveValue('en');
  const second = await context.newPage(); await fixture(second);
  await second.goto('/#/upload');
  await expect(second.locator('#ui-language')).toHaveValue('en');
  await second.locator('#ui-language').selectOption('zh-Hant');
  await expect(page.locator('#ui-language')).toHaveValue('zh-Hant');
  await expect(page.getByRole('heading', { name: '文件庫', exact: true })).toBeVisible();
  await expect(page.locator('.doc-card')).toContainText('设置');
  await second.close();
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

for (const [locale, expected] of [['en-AU', 'en'], ['zh-TW', 'zh-Hant'], ['zh-CN', 'zh-Hans'], ['fr-FR', 'en']]) {
  test(`browser preference ${locale} selects ${expected}`, async ({ browser, baseURL }) => {
    const context = await browser.newContext({ locale, baseURL });
    const page = await context.newPage(); await fixture(page);
    await page.goto('/#/library');
    await expect(page.locator('html')).toHaveAttribute('lang', expected);
    await expect(page.locator('#ui-language')).toHaveValue(expected);
    await context.close();
  });
}

test('blocked storage still permits language switching', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('Blocked', 'SecurityError'); } });
  });
  const { errors } = await fixture(page);
  await page.goto('/#/library');
  await page.locator('#ui-language').selectOption('en');
  await expect(page.getByRole('heading', { name: 'Library', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

for (const width of [390, 1440]) test(`all three languages render and navigate at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const { writes, errors } = await fixture(page);
  await page.goto('/#/library');
  for (const locale of ['en', 'zh-Hant', 'zh-Hans']) {
    if (width < 761) await page.locator('.mobile-menu').click();
    await page.locator('#ui-language').selectOption(locale);
    if (width < 761) {
      await page.locator('#ui-language').press('Tab');
      await expect(page.locator('.side-bottom a')).toBeFocused();
      await page.locator('#ui-language').focus();
      await page.keyboard.press('Escape');
      await expect(page.locator('.mobile-menu')).toBeFocused();
    }
    await expect(page.locator('html')).toHaveAttribute('lang', locale);
    for (const route of ['library', 'upload', 'jobs', 'search', 'glossary', 'memory', 'settings']) {
      await page.goto(`/#/${route}`);
      await expect(page.locator('main h1')).toBeVisible();
      await expect(page.locator('vite-error-overlay')).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${locale} ${route} at ${width}`).toBe(true);
      if (route === 'library' || route === 'settings') await page.screenshot({ path: outputDirectory(`i18n-${locale}-${route}-${width}.png`), fullPage: route === 'library' });
    }
  }
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

test('invalid stored preference falls back to the browser locale', async ({ page }) => {
  await page.addInitScript(key => localStorage.setItem(key, 'unsupported'), storageKey);
  await fixture(page); await page.goto('/#/library');
  await expect(page.locator('#ui-language')).toHaveValue('zh-Hans');
});

test('switching language preserves unsaved editable text, source evidence and selection state', async ({ page }) => {
  const { writes, errors } = await fixture(page);
  const source = '设置 <script>原文证据</script> {id}';
  await page.route('**/api/v1/drafts/i18n', route => route.fulfill({ json: {
    id: 'i18n', document_id: 'doc_i18n', edition_id: 'edition', generation: 1, source_revision_id: 'source',
    source_hash: 'source-hash', target_locale: 'zh-Hans', segments: [{ block_id: 'b1', version: 1, translatable: true,
      source_text: source, source_inline: [{ type: 'text', text: source }], target_inline: [{ type: 'text', text: '原始译文' }],
      source_hash: 'source-b1', context_hash: 'context', review_status: 'not_reviewed' }],
  }, headers: { ETag: '"1"' } }));
  await page.route('**/api/v1/documents/doc_i18n', route => route.fulfill({ json: {
    id: 'doc_i18n', title: '设置', tags: [], generation: 1, lifecycle: 'active', source_revision_id: 'source', editions: [],
  }, headers: { ETag: '"1"' } }));
  await page.goto('/#/drafts/i18n');
  await page.getByRole('button', { name: '展开全部段落', exact: true }).click();
  const segment = page.locator('#segment-b1'), text = '用户修改 設定 <b>hello</b> 😀';
  await segment.locator('[contenteditable="true"]').fill(text);
  await segment.getByLabel('修改理由', { exact: true }).fill('用户输入的理由');
  await page.getByLabel('选择段落 b1', { exact: true }).check();
  for (const locale of ['en', 'zh-Hant', 'zh-Hans']) {
    await page.locator('#ui-language').selectOption(locale);
    await expect(segment.locator('[contenteditable="true"]')).toHaveText(text);
    await expect(segment.locator('.source-block')).toHaveText(source);
    await expect(segment.locator('input[type="checkbox"]').first()).toBeChecked();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  }
  await expect(segment.getByLabel('修改理由', { exact: true })).toHaveValue('用户输入的理由');
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

test('previous upload validation follows the language selection', async ({ page }) => {
  const { writes, errors } = await fixture(page);
  await page.goto('/#/upload');
  await page.locator('input[type="file"]').setInputFiles({ name: 'empty.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(0) });
  await expect(page.getByText('文件为空。', { exact: true })).toBeVisible();
  await page.locator('#ui-language').selectOption('en');
  await expect(page.getByText('The file is empty.', { exact: true })).toBeVisible();
  await page.locator('#ui-language').selectOption('zh-Hant');
  await expect(page.getByText('檔案為空。', { exact: true })).toBeVisible();
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});
