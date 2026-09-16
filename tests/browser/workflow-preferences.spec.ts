import { test, expect, type Page } from '../../apps/web/node_modules/@playwright/test/index.mjs';

const preferences = { generation: 1, locale: 'ja', publish_policy: 'manual_approval', theme: 'light' };
const provider = { generation: 1, configured: true, dispatch_configuration_ready: true, provider: 'openai',
  api_protocol: 'responses', endpoint: 'https://example.invalid/v1/responses', model_id: 'test-model',
  profile_revision: 'profile', profile_hash: 'b'.repeat(64), cost_control_enabled: false };
const document = { id: 'doc', generation: 1, title: 'Preference fixture', source_asset_id: 'asset',
  source_revision_id: 'source', lifecycle: 'active', tags: [], starred: false, editions: [] };
const preflight = { import_id: 'parsed', document_id: 'doc', generation: 1, preflight_generation: 1,
  status: 'ready', source_revision_id: 'source', source_hash: 'a'.repeat(64), source_language: 'en',
  page_count: 1, block_count: 1, unresolved_blocks: 0, can_translate: true,
  blocks: [{ id: 'b1', kind: 'paragraph', normalized_text: 'A complete paragraph.' }] };

async function mock(page: Page, waitForPreferences?: Promise<void>) {
  const writes: { path: string; body: any }[] = [];
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    if (path === '/settings/preferences') {
      await waitForPreferences;
      return route.fulfill({ json: preferences, headers: { ETag: '"1"' } });
    }
    if (!['GET', 'HEAD'].includes(request.method()) && !path.includes('/chunks/')) {
      writes.push({ path, body: request.postDataJSON() });
    }
    const values: Record<string, unknown> = {
      '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'] },
      '/settings/provider': provider, '/documents/doc': document,
      '/imports/parsed/preflight': preflight,
      '/editions/edition/preflight': { ...preflight, profile: provider, profile_hash: provider.profile_hash, locale: 'ja' },
      '/drafts/draft/translation-preflight': { ...preflight, profile: provider, profile_hash: provider.profile_hash, locale: 'ja' },
      '/imports/parsed/confirm': { job_id: 'job' }, '/editions/edition/translate': { job_id: 'job' },
      '/drafts/draft/translate': { job_id: 'job' }, '/documents/doc/parse': { job_id: 'job' },
      '/documents/doc/editions': { id: 'edition' }, '/imports': document,
      '/jobs/job': { id: 'job', stage: 'translate', status: 'pending', generation: 1, control_epoch: 0 },
      '/uploads': { upload_id: 'upload', status: 'created', chunk_limit: 4096, generation: 1 },
      '/uploads/upload/chunks/0': { upload_id: 'upload', status: 'uploading', generation: 2 },
      '/uploads/upload/finalize': { upload_id: 'upload', status: 'verified', generation: 3 },
    };
    return route.fulfill({ json: values[path] ?? { items: [] }, headers: { ETag: '"1"' } });
  });
  return writes;
}

test('upload uses saved language and manual publication defaults in its import request', async ({ page }) => {
  const writes = await mock(page);
  await page.goto('/#/upload');
  await expect(page.getByLabel('默认目标语言', { exact: true })).toHaveValue('ja');
  await expect(page.getByLabel('阅读结果', { exact: true })).toHaveValue('manual_approval');
  await page.locator('#pdf-files').setInputFiles({ name: 'test.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7 test') });
  await page.getByRole('button', { name: '上传并开始处理' }).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body).toMatchObject({
    target_language: 'ja', workflow: { target_locale: 'ja', publish_policy: 'manual_approval' },
  });
});

test('late preferences keep explicit upload draft choices and cannot be bypassed by submission', async ({ page }) => {
  let release!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; });
  await mock(page, waiting);
  await page.goto('/#/upload');
  await page.getByLabel('默认目标语言', { exact: true }).selectOption('fr');
  await page.getByLabel('阅读结果', { exact: true }).selectOption('auto_publish');
  await page.locator('#pdf-files').setInputFiles({ name: 'test.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7 test') });
  await expect(page.getByRole('button', { name: '上传并开始处理' })).toBeDisabled();
  release();
  await expect(page.getByRole('button', { name: '上传并开始处理' })).toBeEnabled();
  await expect(page.getByLabel('默认目标语言', { exact: true })).toHaveValue('fr');
  await expect(page.getByLabel('阅读结果', { exact: true })).toHaveValue('auto_publish');
});

test('parse confirmation applies saved defaults', async ({ page }) => {
  const writes = await mock(page);
  await page.goto('/#/preflight/parsed');
  await expect(page.getByLabel('目标语言', { exact: true })).toHaveValue('ja');
  await expect(page.getByRole('combobox', { name: '发布方式', exact: true })).toHaveValue('manual_approval');
  await page.getByLabel(/同意将必要的源文/).check();
  await page.getByRole('button', { name: '确认外发，开始翻译' }).click();
  expect(writes.find(row => row.path === '/imports/parsed/confirm')?.body).toMatchObject({ locale: 'ja', publish_policy: 'manual_approval' });
});

test('new edition uses saved locale and its translation uses the saved publication default', async ({ page }) => {
  const writes = await mock(page);
  await page.goto('/#/documents/doc');
  await expect(page.getByLabel('新增语言版', { exact: true })).toHaveValue('ja');
  await page.getByRole('button', { name: '新增', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('combobox', { name: '发布方式', exact: true })).toHaveValue('manual_approval');
  await dialog.getByLabel(/同意向上述服务地址/).check();
  await dialog.getByRole('button', { name: '确认外发，翻译此语言版' }).click();
  expect(writes.find(row => row.path === '/documents/doc/editions')?.body.target_locale).toBe('ja');
  expect(writes.find(row => row.path === '/editions/edition/translate')?.body.publish_policy).toBe('manual_approval');
});

test('document parsing honors the saved publication default', async ({ page }) => {
  const writes = await mock(page);
  await page.goto('/#/documents/doc');
  await page.getByRole('button', { name: '解析并生成阅读版' }).click();
  expect(writes.find(row => row.path === '/documents/doc/parse')?.body.workflow).toMatchObject({
    target_locale: 'ja', publish_policy: 'manual_approval',
  });
});

test('continuing translation honors saved publication settings and permits an explicit override', async ({ page }) => {
  const writes = await mock(page);
  await page.route('**/api/v1/imports/parsed/preflight', route => route.fulfill({ json: {
    ...preflight, status: 'sealed', translation_targets: [{ draft_id: 'draft', target_locale: 'ja' }],
  } }));
  await page.goto('/#/preflight/parsed');
  await page.getByRole('button', { name: /开始翻译/ }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('combobox', { name: '发布方式', exact: true })).toHaveValue('manual_approval');
  await dialog.getByRole('combobox', { name: '发布方式', exact: true }).selectOption('auto_publish');
  await dialog.getByRole('checkbox').check();
  await dialog.getByRole('button', { name: '开始翻译未完成内容' }).click();
  expect(writes.find(row => row.path === '/drafts/draft/translate')?.body.publish_policy).toBe('auto_publish');
});
