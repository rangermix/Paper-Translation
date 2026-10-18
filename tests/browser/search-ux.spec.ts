import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { resolve } from 'node:path';
import { outputDirectory } from './paths';

for (const width of [1440, 390]) test(`search groups fixed matches and preserves scope at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const errors: string[] = [], writes: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const document = { id: 'doc', title: 'A very long document title '.repeat(4), editions: [], tags: [] };
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (request.method() !== 'GET') writes.push(path);
    const q = url.searchParams.get('q') ?? '';
    const data = path.endsWith('/search') ? { items: q === 'missing' ? [] : Array.from({ length: 3 }, (_, index) => ({ document_id: 'doc', title: document.title, artifact_id: 'frozen', block_id: `b${index}`, locale: 'zh-Hans', source_text: `A ${q} ${'long source '.repeat(50)}`, target_text: index ? '中文译文' : '' })), next_cursor: q === 'missing' ? null : 'next' }
      : path.endsWith('/documents') ? { items: q === 'missing' ? [] : [document] }
      : path.endsWith('/reading-position') ? { generation: 0, document_id: 'doc', locale: 'zh-Hans', artifact_id: 'frozen', current_artifact: true }
      : path.endsWith('/settings/preferences') ? { generation: 1, theme: 'light' } : { items: [] };
    await route.fulfill({ contentType: 'application/json', headers: { ETag: '"0"' }, body: JSON.stringify(data) });
  });
  await page.goto('/#/search?q=%3Cscript%3E&scope=body&side=source');
  await expect(page.getByRole('heading', { name: '搜索文档', exact: true })).toBeVisible();
  await expect(page.getByLabel('搜索文档', { exact: true })).toHaveValue('<script>');
  await expect(page.getByLabel('搜索范围')).toHaveValue('source');
  await expect(page.getByRole('status').filter({ hasText: '本页 3 处匹配 · 1 篇文档' })).toBeVisible();
  await expect(page.locator('.search-document h2')).toHaveCount(1);
  await expect(page.locator('.search-match mark')).toHaveCount(3);
  await expect(page.locator('.search-document script')).toHaveCount(0);
  expect((await page.locator('.search-match .source-block').first().textContent())!.length).toBeLessThan(250);
  await expect(page.getByText('此段暂无译文', { exact: true })).toBeVisible();
  const match = page.getByRole('link', { name: '打开匹配段落' }).first();
  const href = new URL((await match.getAttribute('href'))!, 'http://localhost');
  expect(href.pathname).toBe('/artifacts/frozen/index.html'); expect(href.hash).toBe('#b-b0');
  expect(href.searchParams.get('return_to')).toContain('scope=body');
  await page.getByRole('button', { name: '下一页结果' }).click();
  await expect(page).toHaveURL(/cursor=next/);
  await page.getByLabel('查找内容').selectOption('title');
  await expect(page).toHaveURL(/scope=title/);
  await expect(page.getByRole('link', { name: '打开文档', exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel('查找内容')).toHaveValue('body');
  await expect(page).toHaveURL(/cursor=next/);
  await page.getByLabel('搜索文档', { exact: true }).fill('missing');
  await page.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(page.getByText('没有已发布正文匹配', { exact: true })).toBeVisible();
  expect(writes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await page.screenshot({ path: resolve(outputDirectory('search-ux'), `search-${width}.png`), fullPage: true });
  expect(errors).toEqual([]);
});
