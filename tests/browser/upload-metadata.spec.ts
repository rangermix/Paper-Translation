import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const title = 'A Controlled Research Paper about Reliable Metadata';
const bibliography = { title, doi: '10.1234/example', doi_url: 'https://doi.org/10.1234/example',
  authors: [{ name: 'Alice Example' }], year: 2020, container: 'Journal of Metadata', service: 'crossref' };

async function upload(page: Page, finalStatus: string) {
  let imported = false, ready = false, reads = 0;
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.slice(7);
    if (path === '/imports') imported = true;
    if (path === '/uploads/upload') {
      reads += 1;
      return route.fulfill({ json: { upload_id: 'upload', status: 'verified',
        metadata_status: ready ? finalStatus : 'pending',
        bibliography: ready && finalStatus === 'succeeded' ? bibliography : null } });
    }
    const values: Record<string, unknown> = {
      '/capabilities': { source_mime_types: ['application/pdf'] },
      '/settings/preferences': { generation: 1, locale: 'zh-Hans', publish_policy: 'auto_publish', theme: 'light' },
      '/settings/provider': { configured: false, generation: 1 },
      '/uploads': { upload_id: 'upload', status: 'receiving', chunk_limit: 4096, generation: 1 },
      '/uploads/upload/chunks/0': { upload_id: 'upload', status: 'receiving', generation: 2 },
      '/uploads/upload/finalize': { upload_id: 'upload', status: 'verified', metadata_status: 'pending', generation: 3 },
      '/imports': { id: 'doc', title: 'uploaded', generation: 1, editions: [] },
    };
    return route.fulfill({ json: values[path] ?? { items: [] }, headers: { ETag: '"1"' } });
  });
  await page.goto('/#/upload');
  await expect(page.getByRole('heading', { name: '上传 PDF', exact: true })).toBeVisible();
  await expect(page.getByText(/上传后自动从 Crossref/)).toBeVisible();
  await expect(page.getByText(/查询仅发送 DOI，或提取的标题与作者/)).toBeVisible();
  await page.getByLabel('生成内容', { exact: true }).selectOption('source');
  await page.locator('#pdf-files').setInputFiles({ name: 'uploaded.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7 fixture') });
  await page.getByRole('button', { name: '上传并开始处理' }).click();
  await expect.poll(() => imported).toBe(true);
  await expect(page.getByRole('link', { name: /已入库/ })).toBeVisible();
  await expect(page.getByText('正在查询文献信息', { exact: true })).toBeVisible();
  return { complete: () => { ready = true; }, reads: () => reads };
}

for (const viewport of [{ width: 1440, height: 1060 }, { width: 390, height: 844 }]) {
  test(`upload shows asynchronous Crossref metadata at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    const state = await upload(page, 'succeeded');
    state.complete();
    await expect(page.getByText(title, { exact: true })).toBeVisible();
    await expect(page.getByText('Alice Example · 2020 · Journal of Metadata', { exact: true })).toBeVisible();
    await expect(page.getByText('Crossref · 文献信息已匹配', { exact: true })).toBeVisible();
    await expect(page.getByText('uploaded.pdf', { exact: true })).toBeVisible();
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    // Terminal metadata must stop polling while the upload page remains open.
    await page.waitForTimeout(2500);
    const stopped = state.reads();
    await page.waitForTimeout(2500);
    expect(state.reads()).toBe(stopped);
    expect(errors).toEqual([]);
    await page.screenshot({ path: outputDirectory(`crossref-upload-${viewport.width}.png`), fullPage: true });
  });
}

for (const status of ['not_found', 'ambiguous', 'failed']) {
  test(`metadata ${status} leaves upload and import usable`, async ({ page }) => {
    const state = await upload(page, status);
    state.complete();
    const message = { not_found: '暂未查到文献信息', ambiguous: '发现多个可能的文献，尚未确认本篇', failed: '文献信息查询未完成' }[status];
    await expect(page.getByText(message!, { exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: /已入库/ })).toHaveAttribute('href', '#/documents/doc');
    await expect(page.getByText('uploaded.pdf', { exact: true })).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
  });
}
