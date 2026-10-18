import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { inputPath } from './paths';

const supplied = process.env.LIBRARY_READER_NAVIGATION_EVIDENCE;
const folder = supplied ? inputPath(supplied) : '';
const server = process.env.LIBRARY_READER_THEME_URL;
test.beforeEach(() => test.skip(!supplied || !server, 'Generate reader-v14 fixtures and serve them with the documented artifact paths.'));

test('long bilingual outline keeps all 42 anchors and bounds six-level indentation on narrow screens', async ({ page }, testInfo) => {
  const fixture = JSON.parse(readFileSync(resolve(folder, 'long', 'fixture.json'), 'utf8'));
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${server}/artifacts/long/index.html`);
  const toc = page.getByRole('navigation', { name: '双语章节' });
  await expect(toc.locator('a')).toHaveCount(42);
  await expect(toc).toContainText('长中文标题');
  await expect(toc).toContainText('Long English chapter title');
  expect(await toc.locator('ul ul ul ul ul ul').count()).toBeGreaterThan(0);
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.evaluate(() => document.fonts.ready);
    const measurements = await toc.evaluate(element => {
      const links = [...element.querySelectorAll<HTMLAnchorElement>('a')];
      const left = Math.min(...links.map(link => link.getBoundingClientRect().left));
      return {
        missing: links.filter(link => !document.getElementById(decodeURIComponent(link.hash.slice(1)))).map(link => link.hash),
        indentation: Math.max(...links.map(link => link.getBoundingClientRect().left - left)),
        narrowest: Math.min(...links.map(link => link.getBoundingClientRect().width)),
        documentWidth: document.documentElement.scrollWidth,
      };
    });
    expect(measurements.missing).toEqual([]);
    expect(measurements.indentation).toBeLessThanOrEqual(64);
    expect(measurements.narrowest).toBeGreaterThanOrEqual(width - 120);
    expect(measurements.documentWidth).toBe(width);
    await testInfo.attach(`outline-measurements-${width}`, { body: JSON.stringify(measurements), contentType: 'application/json' });
    await toc.locator('a').first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`long-outline-${width}.png`) });
    const last = fixture.heading_ids.at(-1);
    await toc.locator(`a[href="#b-${last}"]`).click();
    await expect(page.locator(`[id="b-${last}"]`)).toBeInViewport();
  }
  expect(errors).toEqual([]);
});

for (const version of ['3.0', '4.0']) {
  test(`${version} online reader returns to its document and original search with fixed anchors`, async ({ page }, testInfo) => {
    const fixture = JSON.parse(readFileSync(resolve(folder, version, 'fixture.json'), 'utf8'));
    const search = '#/search?q=memory%20%26%20notes&offset=30';
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${server}/artifacts/${version}/index.html?return_to=${encodeURIComponent(search)}#b-${fixture.heading_id}`);
    await expect(page.getByRole('link', { name:'返回文档', exact:true })).toHaveAttribute('href', `/#/documents/${fixture.document_id}`);
    await expect(page.getByRole('link', { name:'返回搜索结果', exact:true })).toHaveAttribute('href', '/' + search);
    const toc = page.getByRole('navigation', { name:'双语章节' });
    await expect(toc).toContainText('阅读偏好与章节导航 / ');
    const section = page.locator(`[id="b-${fixture.heading_id}"]`);
    await expect(section).toBeVisible();
    await toc.locator(`a[href="#b-${fixture.heading_id}"]`).click();
    expect(new URL(page.url()).hash).toBe(`#b-${fixture.heading_id}`);
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height:844 });
      // A real scroll key releases the reading anchor before pending resize
      // observers reposition it. Scripted scrollTo races that intended behavior.
      await page.keyboard.press('Control+Home');
      await expect(page.getByRole('link', { name:'返回文档', exact:true })).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
      await page.screenshot({ path:testInfo.outputPath(`navigation-${width}.png`) });
    }
    await page.emulateMedia({ media:'print' });
    await expect(page.locator('[data-online-reader]')).toBeHidden();
    expect(errors).toEqual([]);
  });

  test(`${version} return context cannot redirect outside search and local copies have no server links`, async ({ page, context }) => {
    for (const value of ['https://example.org', 'javascript:alert(1)', '#/settings', '#/searching', '//example.org']) {
      await page.goto(`${server}/artifacts/${version}/index.html?return_to=${encodeURIComponent(value)}`);
      await expect(page.locator('[data-return-search]')).toBeHidden();
      await expect(page.getByRole('link', { name:'返回文档', exact:true })).toBeVisible();
    }
    await context.setOffline(true);
    for (const format of ['published/index.html', 'single.html', 'bundle/index.html']) {
      await page.goto(pathToFileURL(resolve(folder, version, format)).href);
      await expect(page.locator('[data-online-reader]')).toHaveCount(0);
      await expect(page.locator('article')).toBeVisible();
      await expect(page.getByRole('navigation', { name:'双语章节' })).toContainText('阅读偏好与章节导航');
    }
  });

  test(`${version} no-script online return works while exports are independent`, async ({ browser }, testInfo) => {
    const context = await browser.newContext({ javaScriptEnabled:false });
    try {
      const page = await context.newPage();
      await page.goto(`${server}/artifacts/${version}/index.html`);
      await expect(page.getByRole('link', { name:'返回文档', exact:true })).toBeVisible();
      await expect(page.locator('article')).toBeVisible();
      for (const format of ['single.html', 'bundle/index.html']) {
        await page.goto(pathToFileURL(resolve(folder, version, format)).href);
        await expect(page.locator('[data-online-reader]')).toHaveCount(0);
        await expect(page.locator('article')).toBeVisible();
      }
      await page.screenshot({ path: testInfo.outputPath('navigation-no-javascript.png') });
    } finally { await context.close(); }
  });
}
