import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const title = 'A very long research paper title about reliable scientific translation, immutable reading versions and carefully preserved source evidence';
const document = { id: 'doc', generation: 7, title, tags: ['Systems'], starred: false, lifecycle: 'active', status: 'published',
  source_asset_id: 'pdf', source_revision_id: 'source', current_job_id: 'job', current_job_status: 'running' as string | null, page_count: 12, sha256: 'a'.repeat(64), byte_size: 100000,
  bibliography: { title, authors: [{ name: 'Alice Example' }, { name: 'Bob Example' }, { name: 'Chen Example' }, { name: 'Dana Example' }], year: 2026 },
  editions: [{ id: 'edition', target_locale: 'zh-Hans', current_artifact_id: 'current', draft_id: 'draft', generation: 9 }] };
const version = (id: string, date: string, locale = 'zh-Hans') => ({ id, edition_id: locale === 'ja' ? 'edition-ja' : 'edition', locale,
  template_id: id === 'old' ? 'reader-v1' : 'reader-v13', source_revision_id: 'source', translation_revision_id: `translation-${id}`, created_at: date, state: 'verified' });
const history = { sources: [{ id: 'source', created_at: '2026-10-01T00:00:00Z' }], translations: [{ id: 'sealed-only', source_revision_id: 'source', edition_id: 'edition' }],
  artifacts: [version('old', '2026-09-01T00:00:00Z'), version('tie-z', '2026-10-15T00:00:00Z'), version('preview', '2026-10-17T00:00:00Z'), version('current', '2026-10-02T00:00:00Z'), version('tie-a', '2026-10-15T00:00:00Z')],
  publications: [{ id: 'publication-current', artifact_id: 'current', generation: 9, operation: 'publish' }, { id: 'publication-old', artifact_id: 'old', generation: 8, operation: 'publish' }] };
const draft = { id: 'draft', document_id: 'doc', edition_id: 'edition', source_revision_id: 'source', source_hash: 'a'.repeat(64), generation: 4, target_locale: 'zh-Hans',
  segments: [{ block_id: 'missing', translatable: true, target_inline: [], source_text: 'Original text.' }] };

async function setup(page: Page) {
  const state = { doc: structuredClone(document), history: structuredClone(history), exportStatus: 'running', reads: 0 };
  const writes: { path: string; body: any; etag?: string }[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') writes.push({ path, body: request.postDataJSON(), etag: request.headers()['if-match'] });
    if (path === '/documents/doc') state.reads++;
    const values: Record<string, unknown> = {
      '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'] },
      '/settings/preferences': { generation: 1, locale: 'zh-Hans', theme: 'light' },
      '/settings/provider': { configured: false }, '/settings/dispatch': { generation: 1, dispatch_disabled: false },
      '/documents': { items: [state.doc, { ...state.doc, id: 'no-metadata', title: '没有作者信息的文档', bibliography: undefined, editions: [] }], next_cursor: null },
      '/documents/doc': state.doc, '/documents/doc/history': state.history,
      '/drafts/draft': draft, '/drafts/draft/exports': { export_id: 'export' },
      '/templates': { items: [{ id: 'reader-v16', name: '多语言双语阅读' }, { id: 'reader-v14', name: '双语目录与文库导航' }, { id: 'reader-v13', name: '双语对照阅读' }] },
      '/reading-position': { generation: 0, block_id: null },
      '/exports/export': { id: 'export', status: state.exportStatus, download_url: '/api/v1/exports/export/download', ...(state.exportStatus === 'failed' ? { error: { message: 'Synthetic export failed' } } : {}) },
      '/jobs/job': { id: 'job', generation: 1, status: 'pending', stage: 'render', control_epoch: 0 },
    };
    await route.fulfill({ json: path.match(/^\/artifacts\/[^/]+\/exports$/) ? { export_id: 'export' }
      : path.endsWith('/rebuild') ? { job_id: 'job' } : values[path] ?? { items: [] }, headers: { ETag: path === '/drafts/draft' ? '"4"' : '"7"' } });
  });
  return { state, writes, errors };
}

test('document processing link uses the selected job status instead of the publication status', async ({ page }) => {
  const { state, writes } = await setup(page);
  for (const [status, label] of [['running', '查看处理进度'], ['failed', '最近处理记录'], ['outcome_unknown', '查看处理进度'], [null, '查看处理记录']] as const) {
    state.doc.current_job_status = status;
    await page.goto('/#/library');
    await expect(page.locator('.doc-card').first().getByRole('link', { name:label, exact:true })).toHaveAttribute('href', '#/jobs/job');
    await page.goto('/#/documents/doc');
    await expect(page.getByRole('link', { name:label, exact:true })).toHaveAttribute('href', '#/jobs/job');
  }
  expect(writes).toEqual([]);
});

for (const width of [390, 404]) test(`compact mobile library keeps full titles and original PDF reachable at ${width}px`, async ({ page }) => {
  const { writes, errors } = await setup(page);
  await page.setViewportSize({ width, height: 844 });
  await page.goto('/#/library');
  const card = page.locator('.doc-card').first();
  await expect(card.getByRole('link', { name: '阅读', exact: true })).toBeVisible();
  await expect(card.getByRole('link', { name: '原文 PDF', exact: true })).toHaveAttribute('href', '/api/v1/documents/doc/original');
  expect((await card.boundingBox())!.height).toBeLessThan(390);
  const disclosure = card.locator('.doc-full-title summary');
  await disclosure.focus();
  await page.keyboard.press('Enter');
  await expect(card.locator('.doc-full-title p')).toHaveText(title);
  await expect(card.locator('.doc-full-title p')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory(`library-${width}.png`), fullPage: true });
  expect(writes).toEqual([]); expect(errors).toEqual([]);
});

test('current version is first even when older, followed by stable newest-first previews and history', async ({ page }) => {
  const { writes } = await setup(page);
  await page.goto('/#/history/doc');
  const versions = page.locator('[data-artifact-id]');
  await expect(versions).toHaveCount(5);
  expect(await versions.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-artifact-id')))).toEqual(['current', 'preview', 'tie-a', 'tie-z', 'old']);
  await expect(versions.nth(0).getByText('当前阅读版', { exact: true })).toBeVisible();
  await expect(versions.nth(1).getByText('未发布 · 可预览', { exact: true })).toBeVisible();
  await expect(versions.nth(4).getByText('历史阅读版', { exact: true })).toBeVisible();
  await expect(versions.nth(4).getByText('reader-v1', { exact: true })).not.toBeVisible();
  await versions.nth(4).locator('.technical-details > summary').click();
  await expect(versions.nth(4).getByText('reader-v1', { exact: true })).toBeVisible();
  await page.getByText('已封存内容（原文 1 · 译文 1）', { exact: true }).click();
  await expect(page.getByText('封存内容是不可修改的内容快照；阅读版本由这些快照生成，可使用不同阅读样式。')).toBeVisible();
  expect(writes).toEqual([]);
  await page.screenshot({ path: outputDirectory('history-order.png'), fullPage: true });
});

test('document export holds its selected immutable target while the current pointer changes', async ({ page }) => {
  const { state, writes } = await setup(page);
  await page.goto('/#/documents/doc');
  await expect(page.getByText('a'.repeat(64), { exact: true })).not.toBeVisible();
  await page.getByRole('button', { name: '导出当前版', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '导出此版本', exact: true });
  await expect(dialog).toContainText(title);
  await expect(dialog.getByLabel('阅读版本', { exact: true })).toHaveValue('current');
  const reads = state.reads;
  state.doc.editions[0].current_artifact_id = 'preview';
  state.doc.editions[0].generation = 10;
  await expect.poll(() => state.reads, { timeout: 8000 }).toBeGreaterThan(reads);
  await expect(dialog.getByLabel('阅读版本', { exact: true })).toHaveValue('current');
  await dialog.getByLabel('导出格式', { exact: true }).selectOption('bundle');
  await expect(dialog.getByText('将网页和所需资源打包为 ZIP，解压后打开 index.html 离线阅读。')).toBeVisible();
  await dialog.getByLabel('同时打包原文 PDF', { exact: true }).check();
  await dialog.getByRole('button', { name: '生成下载文件', exact: true }).click();
  await expect.poll(() => writes.find(write => write.path.includes('/exports'))).toMatchObject({ path: '/artifacts/current/exports', body: { format: 'bundle', include_source: true } });
  await expect(dialog.getByLabel('阅读版本', { exact: true })).toBeDisabled();
  await expect(dialog.getByRole('button', { name: '正在生成下载文件…', exact: true })).toBeDisabled();
  state.exportStatus = 'succeeded';
  await expect(dialog.getByRole('link', { name: '下载文件', exact: true })).toHaveAttribute('href', '/api/v1/exports/export/download');
});

test('explicit historical export keeps that version and failures offer safe option reset', async ({ page }) => {
  const { state, writes } = await setup(page);
  await page.goto('/#/history/doc');
  await page.locator('[data-artifact-id="old"]').getByRole('button', { name: '导出此版本', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('阅读版本', { exact: true })).toHaveValue('old');
  state.exportStatus = 'failed';
  await dialog.getByRole('button', { name: '生成下载文件', exact: true }).click();
  await expect.poll(() => writes[0]?.path).toBe('/artifacts/old/exports');
  await expect(dialog.getByRole('alert').filter({ hasText: '本次操作未完成，请查看技术详情或稍后重试。' })).toBeVisible();
  await dialog.getByText('错误技术详情', { exact: true }).click();
  await expect(dialog.getByText('Synthetic export failed', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: '重新选择导出选项', exact: true }).click();
  await expect(dialog.getByLabel('阅读版本', { exact: true })).toHaveValue('old');
  await expect(dialog.getByRole('button', { name: '生成下载文件', exact: true })).toBeEnabled();
});

test('draft-only document exports saved content with a missing-translation notice and original CAS', async ({ page }) => {
  const { state, writes } = await setup(page);
  state.doc.editions[0].current_artifact_id = '';
  await page.goto('/#/documents/doc');
  await page.getByRole('button', { name: '导出当前草稿', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '导出当前草稿', exact: true });
  await expect(dialog).toContainText(title);
  await expect(dialog).toContainText('缺译 1 段');
  await expect(dialog).toContainText('缺失译文的段落将保留原文');
  await dialog.getByRole('button', { name: '生成下载文件', exact: true }).click();
  await expect.poll(() => writes.find(write => write.path === '/drafts/draft/exports')).toEqual({ path: '/drafts/draft/exports', etag: '"4"', body: { format: 'single_html', include_source: false, confirm_draft: true } });
});

test('style action creates a preview with unchanged CAS semantics', async ({ page }) => {
  const { writes } = await setup(page);
  await page.goto('/#/history/doc');
  const current = page.locator('[data-artifact-id="current"]');
  await current.getByText('阅读样式与发布操作', { exact: true }).click();
  await current.getByRole('button', { name: '用所选样式生成预览', exact: true }).click();
  await expect.poll(() => writes.find(write => write.path === '/artifacts/current/rebuild')?.body).toEqual({ template_id: 'reader-v16', preview_only: true, expected_generation: 9 });
  expect(writes.some(write => write.path.endsWith('/rollback') || write.path.endsWith('/unpublish'))).toBe(false);
});
