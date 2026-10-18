import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const document = { id: 'doc-a', generation: 1, title: 'Shared paper title', original_filename: 'first.pdf', tags: [], starred: false, lifecycle: 'active', source_asset_id: 'pdf',
  bibliography: { authors: [{ name: 'Alice Example' }], year: 2026 }, editions: [{ id: 'edition', target_locale: 'zh-Hans', draft_id: 'draft' }] };
const glossary = { id: 'g1', generation: 1, source_language: 'en', target_language: 'zh-Hans', scope: 'global', document_id: null, created_at: '2026-10-01T00:00:00Z',
  entries: [{ source: 'memory', target: '记忆', mode: 'preferred', variants: ['memories'], note: 'Keep original note', case_sensitive: true }] };

async function setup(page: Page, kind: 'empty' | 'unreviewed' | 'reviewed' | 'existing' = 'unreviewed') {
  const state = { versions: [structuredClone(glossary), { ...structuredClone(glossary), id: 'g2', entries: [{ ...glossary.entries[0], target: '内存' }] }],
    documents: kind === 'empty' ? [] : [structuredClone(document), { ...structuredClone(document), id: 'doc-b', original_filename: 'second.pdf', bibliography: { authors: [{ name: 'Bob Example' }], year: 2025 } }],
    deleted: false, failSave: false,
    memories: kind === 'existing' ? [{ id: 'm1', generation: 3, source_text: 'A saved source', target_text: '一条已保存译文', target_language: 'zh-Hans', document_id: 'doc-a', independent: false }] : [],
  };
  const writes: { path: string; body: any; etag?: string }[] = [];
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.slice(7);
    if (request.method() !== 'GET') writes.push({ path, body: request.postData() ? request.postDataJSON() : null, etag: request.headers()['if-match'] });
    if (path === '/glossaries/revisions') {
      if (state.failSave) return route.fulfill({ status: 503, json: { error: { code: 'SAVE_FAILED', message: 'Synthetic save unavailable' } } });
      const next = { ...request.postDataJSON(), id: `saved-${state.versions.length}`, generation: 1, created_at: '2026-10-18T00:00:00Z' };
      state.versions.unshift(next); return route.fulfill({ json: next });
    }
    if (path.match(/^\/glossaries\/[^/]+\/impact$/)) return route.fulfill({ json: { items: [] } });
    if (path.startsWith('/documents/')) {
      const found = state.documents.find(item => item.id === path.split('/')[2]);
      return route.fulfill({ status: state.deleted || !found ? 404 : 200, json: state.deleted || !found ? { error: { code: 'NOT_FOUND', message: 'Document unavailable' } } : found });
    }
    const values: Record<string, unknown> = {
      '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'] }, '/settings/preferences': { generation: 1, locale: 'zh-Hans', theme: 'light' },
      '/settings/provider': { configured: false }, '/settings/dispatch': { generation: 1, dispatch_disabled: false },
      '/glossaries': { items: state.versions },
      '/documents': { items: url.searchParams.get('q') === 'missing' ? [] : state.documents },
      '/translation-memory': { items: url.searchParams.has('q') ? [] : state.memories },
      '/drafts/draft': { id: 'draft', document_id: 'doc-a', generation: 1, target_locale: 'zh-Hans', segments: [{ block_id: 'b1', translatable: true, target_inline: [{ type: 'text', text: '已有译文' }], review_status: kind === 'reviewed' ? 'human_reviewed' : 'unreviewed' }] },
    };
    return route.fulfill({ json: values[path] ?? { items: [] }, headers: { ETag: '"1"' } });
  });
  return { state, writes };
}

async function addTerm(page: Page, source = 'cache', target = '缓存') {
  await page.getByLabel('原文术语', { exact: true }).fill(source);
  await page.getByLabel('译法', { exact: true }).fill(target);
  await page.getByRole('button', { name: '添加词条', exact: true }).click();
}

test('document title selection disambiguates duplicates and preview uses the saved version without saving', async ({ page }) => {
  const { writes } = await setup(page);
  await page.goto('/#/glossary');
  await page.getByLabel('编辑基准', { exact: true }).selectOption('g1');
  await addTerm(page);
  await expect(page.getByText('预览使用当前编辑基准，不包含未保存修改。')).toBeVisible();
  const select = page.getByLabel('预览范围', { exact: true });
  await expect(select.locator('option[value="doc-a"]')).toContainText('Alice Example · 2026 · first.pdf');
  await expect(select.locator('option[value="doc-b"]')).toContainText('Bob Example · 2025 · second.pdf');
  await select.selectOption('doc-b');
  await page.getByRole('button', { name: '预览受影响段落', exact: true }).click();
  await expect.poll(() => writes[0]?.body).toEqual({ document_id: 'doc-b' });
  expect(writes[0].path).toBe('/glossaries/g1/impact');
  await expect(page.getByText('所选范围内没有匹配段落。')).toBeVisible();
  await select.selectOption('');
  await page.getByRole('button', { name: '预览受影响段落', exact: true }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1].body).toEqual({ document_id: null });
  expect(writes.some(write => write.path === '/glossaries/revisions')).toBe(false);
});

test('switching glossary bases protects added and unfinished terms; a failed save keeps the working copy', async ({ page }) => {
  const { state, writes } = await setup(page);
  await page.goto('/#/glossary');
  await page.getByLabel('编辑基准', { exact: true }).selectOption('g1');
  await addTerm(page);
  await page.getByLabel('编辑基准', { exact: true }).selectOption('g2');
  const dialog = page.getByRole('dialog', { name: '术语表有未保存修改', exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: '继续编辑', exact: true }).click();
  await expect(page.getByLabel('编辑基准', { exact: true })).toHaveValue('g1');
  await expect(page.getByRole('cell', { name: '缓存', exact: false })).toBeVisible();
  state.failSave = true;
  await page.getByRole('button', { name: '保存新版本', exact: true }).click();
  const error = page.getByRole('alert');
  await expect(error).toContainText('本次操作未完成');
  await error.getByText('技术详情', { exact: true }).click();
  await expect(error.getByText('Synthetic save unavailable', { exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: '缓存', exact: false })).toBeVisible();
  state.failSave = false;
  await page.getByLabel('原文术语', { exact: true }).fill('unfinished');
  await page.getByRole('link', { name: '文档库', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '保存后继续', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: '继续编辑', exact: true }).click();
  await expect(page.getByLabel('原文术语', { exact: true })).toHaveValue('unfinished');
  expect(writes.filter(write => write.path === '/glossaries/revisions')).toHaveLength(1);
});

test('saving creates an independent revision and preserves concurrently added versions and entry metadata', async ({ page }) => {
  const { state, writes } = await setup(page);
  await page.goto('/#/glossary?document=doc-b');
  await expect(page.getByLabel('选择文档', { exact: true })).toHaveValue('doc-b');
  await page.getByLabel('编辑基准', { exact: true }).selectOption('g1');
  const row = page.getByRole('row').filter({ hasText: 'memory' });
  await row.getByRole('button', { name: '修改', exact: true }).click();
  await page.getByLabel('译法', { exact: true }).fill('内存术语');
  await page.getByRole('button', { name: '更新词条', exact: true }).click();
  state.versions.unshift({ ...structuredClone(glossary), id: 'other-window' });
  await page.getByRole('button', { name: '刷新版本列表', exact: true }).click();
  await expect(page.getByLabel('编辑基准', { exact: true }).locator('option[value="other-window"]')).toHaveCount(1);
  await expect(page.getByRole('cell', { name: /内存术语/ })).toBeVisible();
  await page.getByRole('button', { name: '保存新版本', exact: true }).click();
  await expect.poll(() => writes.find(write => write.path === '/glossaries/revisions')?.body.entries[0]).toMatchObject({ target: '内存术语', case_sensitive: true, note: 'Keep original note', variants: ['memories'] });
  expect(writes.find(write => write.path === '/glossaries/revisions')?.etag).toBeUndefined();
  expect(state.versions.some(version => version.id === 'other-window')).toBe(true);
  expect(state.versions.find(version => version.id === 'g1')?.entries[0].target).toBe('记忆');
});

test('deleted document selection and empty title search cannot silently change the save scope', async ({ page }) => {
  const { state, writes } = await setup(page);
  state.deleted = true;
  await page.goto('/#/glossary?document=doc-b');
  await addTerm(page);
  await expect(page.getByText('所选文档已删除或暂不可用，请重新选择。词条修改仍保留。')).toBeVisible();
  await expect(page.getByRole('button', { name: '保存新版本', exact: true })).toBeDisabled();
  const group = page.getByRole('group', { name: '选择文档选择器', exact: true });
  await group.getByRole('textbox').fill('missing');
  await group.getByRole('button', { name: '查找文档', exact: true }).click();
  await expect(group.getByText('没有找到匹配的文档，请换一个标题。')).toBeVisible();
  await expect(group.getByRole('combobox')).toHaveValue('doc-b');
  expect(writes).toEqual([]);
});

test('a document glossary preview stays bound to its saved document while edits remain separate', async ({ page }) => {
  const { state, writes } = await setup(page);
  Object.assign(state.versions[0], { scope: 'document', document_id: 'doc-a' });
  await page.goto('/#/glossary?document=doc-b');
  await page.getByLabel('编辑基准', { exact: true }).selectOption('g1');
  await page.getByLabel('选择文档', { exact: true }).selectOption('doc-b');
  await expect(page.getByText('此版本仅适用于关联文档：Shared paper title', { exact: true })).toBeVisible();
  await expect(page.getByLabel('预览范围', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '预览受影响段落', exact: true }).click();
  await expect.poll(() => writes[0]?.body).toEqual({ document_id: 'doc-a' });
  expect(writes[0].path).toBe('/glossaries/g1/impact');
  expect(writes).toHaveLength(1);
});

test('base switching saves or discards only after an explicit choice', async ({ page }) => {
  const { state, writes } = await setup(page);
  await page.goto('/#/glossary');
  await page.getByLabel('编辑基准', { exact: true }).selectOption('g1');
  await addTerm(page);
  await page.getByLabel('编辑基准', { exact: true }).selectOption('g2');
  const dialog = page.getByRole('dialog', { name: '术语表有未保存修改', exact: true });
  await dialog.getByRole('button', { name: '保存后继续', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel('编辑基准', { exact: true })).toHaveValue('g2');
  expect(state.versions.find(version => version.id.startsWith('saved-'))?.entries).toHaveLength(2);
  await addTerm(page, 'discarded', '不保存');
  await page.getByLabel('编辑基准', { exact: true }).selectOption('g1');
  await dialog.getByRole('button', { name: '放弃修改', exact: true }).click();
  await expect(page.getByLabel('编辑基准', { exact: true })).toHaveValue('g1');
  await expect(page.getByRole('cell', { name: 'discarded', exact: true })).toHaveCount(0);
  expect(writes.filter(write => write.path === '/glossaries/revisions')).toHaveLength(1);
});

test('document context and mobile glossary controls remain usable with long titles', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { state } = await setup(page);
  state.documents[0].title = 'A very long document title with a multilingual subtitle '.repeat(4);
  await page.goto('/#/documents/doc-a');
  const link = page.getByRole('link', { name: '管理本篇术语', exact: true });
  await expect(link).toHaveAttribute('href', '#/glossary?document=doc-a');
  await link.click();
  await expect(page.getByLabel('选择文档', { exact: true })).toHaveValue('doc-a');
  await expect(page.getByLabel('预览范围', { exact: true })).toHaveValue('doc-a');
  await addTerm(page, 'Long unbroken term'.repeat(5), '长术语'.repeat(20));
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: outputDirectory('glossary-390.png'), fullPage: true });
});

for (const kind of ['empty', 'unreviewed', 'reviewed', 'existing'] as const) test(`memory ${kind} state offers an honest next step without creating records`, async ({ page }) => {
  const { writes } = await setup(page, kind);
  await page.goto('/#/memory');
  if (kind === 'existing') {
    await expect(page.getByRole('button', { name: '查找记忆', exact: true })).toBeVisible();
    await expect(page.getByText('一条已保存译文', { exact: true })).toBeVisible();
  } else {
    await expect(page.getByRole('heading', { name: '还没有保存的译文片段', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '查找记忆', exact: true })).toHaveCount(0);
    const name = kind === 'empty' ? '上传第一篇 PDF' : kind === 'reviewed' ? '查看已核对译文' : '打开译文并核对';
    await expect(page.getByRole('link', { name, exact: true })).toHaveAttribute('href', kind === 'empty' ? '#/upload' : '#/drafts/draft');
  }
  expect(writes).toEqual([]);
  if (kind === 'reviewed') await page.screenshot({ path: outputDirectory('memory-start.png'), fullPage: true });
});
