import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';

async function fixture(page: Page) {
  const errors: string[] = [], writes: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const segment = (id: string) => ({ block_id: id, version: 1, translatable: true, source_text: `Source ${id} 设置`,
    source_inline: [{ type: 'text', text: `Source ${id} 设置` }], target_inline: [{ type: 'text', text: `译文 ${id}` }],
    source_hash: `source-${id}`, context_hash: 'context', review_status: 'not_reviewed' });
  const draft = { id: 'audit', document_id: 'doc', edition_id: 'edition', generation: 1, source_revision_id: 'source',
    source_hash: 'source-hash', target_locale: 'zh-Hans', segments: [segment('b1'), segment('b2')],
    qa: { id: 'qa', generation: 1, fingerprint: 'qa-hash', state: 'completed', issues: [
      { id: 'table', severity: 'important', category: 'table', stage: 'source_check', block_id: 'b1', message: '表格内容与原 PDF 可能不同' },
      { id: 'layout', severity: 'info', category: 'typography', stage: 'source_check', block_id: 'b2', message: '文字排版与原 PDF 有细微差异' },
    ] } };
  let latest = false;
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice('/api/v1'.length);
    if (request.method() !== 'GET') writes.push(path);
    if (request.method() === 'PATCH' && path.startsWith('/drafts/audit/segments/')) {
      if (path.endsWith('/b2')) return route.fulfill({ status: 412, json: { error: { code: 'PRECONDITION_FAILED', message: '原始诊断 <unaltered>' } } });
      draft.segments[0].target_inline = request.postDataJSON().target_inline;
      draft.segments[0].version++; draft.generation++;
      return route.fulfill({ json: draft, headers: { ETag: `"${draft.generation}"` } });
    }
    const data: Record<string, unknown> = {
      '/capabilities': {}, '/settings/preferences': { generation: 1, theme: 'light', locale: 'zh-Hans', parser_profile_revision: 'surya-ocr-2-v1', parser_timeout_seconds: 7200 },
      '/settings/provider': { generation: latest ? 2 : 1, configured: true, dispatch_configuration_ready: true, config_source: 'managed',
        provider: latest ? 'anthropic' : 'openai', api_protocol: latest ? 'claude_messages' : 'responses', auth_mode: latest ? 'api_key' : 'none',
        endpoint: 'https://synthetic.invalid/v1/messages', model_id: 'synthetic-model', api_version: '2023-06-01',
        has_api_key: false, cost_control_enabled: false, profile_hash: 'a'.repeat(64) },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false, unknown_attempts: 0 },
      '/settings/parser-models': { models: [] }, '/settings/local-models': { models: [] },
      '/settings/resources': { waiting_jobs: [], model_references: [] }, '/settings/parser-environment': { options: [] },
      '/documents/doc': { id: 'doc', title: '设置 <user title>', tags: [], generation: 1, lifecycle: 'active', source_revision_id: 'source', editions: [] },
      '/drafts/audit': draft,
      '/imports/audit/preflight': { import_id: 'audit', document_id: 'doc', generation: 1, preflight_generation: 1, source_revision_id: 'source', source_hash: 'source-hash',
        status: 'ready', source_language: 'en', page_count: 1, block_count: 1, unresolved_blocks: 0, issues: [],
        blocks: [{ id: 'b1', kind: 'paragraph', source_text: 'Paragraph 原文' }], assets: [{ id: 'image-1', kind: 'image/png', page: 1, status: 'available' }] },
    };
    return route.fulfill({ json: data[path] ?? { items: [], total: 0 }, headers: { ETag: `"${latest ? 2 : draft.generation}"` } });
  });
  return { errors, writes, showLatest: () => { latest = true; } };
}

test('parse block and asset enums are localized without changing source text or IDs', async ({ page }) => {
  const { errors, writes } = await fixture(page);
  await page.goto('/#/preflight/audit');
  await page.locator('#ui-language').selectOption('en');
  await expect(page.locator('#source-preview option')).toHaveText('1. Paragraph · Paragraph 原文');
  await page.getByText('View figures and tables (1)', { exact: true }).click();
  await expect(page.getByText('image/png · image-1 · Page 1 · Available', { exact: true })).toBeVisible();
  await page.locator('#ui-language').selectOption('zh-Hant');
  await expect(page.locator('#source-preview option')).toHaveText('1. 段落 · Paragraph 原文');
  await expect(page.locator('.source-block')).toHaveText('Paragraph 原文');
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

test('editor categories and already-created parameterized feedback switch languages', async ({ page }) => {
  const { errors, writes } = await fixture(page);
  await page.goto('/#/drafts/audit');
  await page.locator('.editor-check-results > summary').click();
  await page.getByRole('button', { name: '展开全部段落', exact: true }).click();
  await page.locator('#segment-b1 [contenteditable=true]').fill('User edit <unchanged>');
  await page.getByRole('button', { name: /保存修改/ }).click();
  await page.locator('#ui-language').selectOption('en');
  await expect(page.getByText('1 segments still need a translation or a reason for the change. Continue editing.', { exact: true })).toBeVisible();
  await expect(page.locator('.editor-quality option[value=table]')).toHaveText('Table content');
  await expect(page.locator('.editor-quality option[value=typography]')).toHaveText('Layout');
  await page.locator('#reason-b1').fill('User reason');
  await page.locator('#segment-b2 [contenteditable=true]').fill('Unsaved second edit');
  await page.locator('#reason-b2').fill('Second reason');
  await page.locator('#ui-language').selectOption('zh-Hans');
  await page.getByRole('button', { name: /保存修改/ }).click();
  await expect.poll(() => writes.length).toBe(2);
  await page.locator('#ui-language').selectOption('en');
  await expect(page.getByText('Saved 1 segments; 1 segments remain unsaved.', { exact: true })).toBeVisible();
  await expect(page.locator('#segment-b2')).toContainText('The server version has changed.');
  await page.locator('#ui-language').selectOption('zh-Hant');
  await expect(page.getByText('已保存 1 段；其餘 1 段仍未保存。', { exact: true })).toBeVisible();
  await expect(page.locator('#segment-b2 [contenteditable=true]')).toHaveText('Unsaved second edit');
  await expect(page.locator('#reason-b2')).toHaveValue('Second reason');
  expect(errors).toEqual([]);
});

test('settings conflict comparison localizes protocol and authentication enums', async ({ page }) => {
  const { errors, writes, showLatest } = await fixture(page);
  await page.goto('/#/settings');
  await page.getByLabel('模型 ID', { exact: true }).fill('unsaved-model');
  showLatest();
  await page.getByRole('button', { name: '刷新配置', exact: true }).click();
  await page.getByRole('dialog', { name: '刷新设置并保留输入' }).getByRole('button', { name: '刷新并保留输入' }).click();
  await page.locator('#ui-language').selectOption('en');
  const comparison = page.getByRole('region', { name: 'Configuration version comparison' });
  await expect(comparison).toContainText('Claude Messages (native) / API key (x-api-key)');
  await expect(comparison).not.toContainText('claude_messages / api_key');
  await expect(page.getByLabel('Model ID', { exact: true })).toHaveValue('unsaved-model');
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});
