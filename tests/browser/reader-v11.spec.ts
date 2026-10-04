import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { inputPath } from './paths';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const supplied = process.env.LIBRARY_READER_V11_EVIDENCE;
const folder = supplied ? inputPath(supplied) : '';
test.beforeEach(() => test.skip(!supplied, 'Set LIBRARY_READER_V11_EVIDENCE to the authored rich reader fixture.'));

for (const format of ['single.html', 'bundle/index.html']) {
  test(`${format} preserves title metadata, nested citations and collected footnotes`, async ({ page, context }, testInfo) => {
    const errors: string[] = [], outbound: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (['error', 'warning'].includes(message.type())) errors.push(message.text()); });
    page.on('request', request => { if (/^https?:/.test(request.url())) outbound.push(request.url()); });
    await context.setOffline(true);
    await page.setViewportSize({ width: 1440, height: 1060 });
    const url = pathToFileURL(resolve(folder, format)).href;
    await page.goto(url);
    expect(page.url()).toBe(url);
    expect(await page.title()).not.toBe('');
    await expect(page.locator('article')).toBeVisible();
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    await expect(page.locator('header .title-metadata')).toContainText('Jane Smith');
    await expect(page.locator('header .title-metadata')).toContainText('Example University');
    await expect(page.locator('header [data-original-only="original_author_list"] [data-language="target"]')).toHaveCount(0);

    const block = page.locator('section.pair').filter({ has: page.locator('.en').filter({ hasText: 'Our implementation' }) });
    const citation = block.locator('[data-language="source"] a[data-reference-targets]').last();
    const row = block.locator('..');
    await citation.scrollIntoViewIfNeeded();
    await citation.focus();
    const before = await page.evaluate(() => scrollY);
    await page.keyboard.press('Enter');
    await expect(row.locator('.reference-card')).toBeVisible();
    await expect(row.locator('.reference-card')).toContainText('Second result');
    expect(Math.abs(await page.evaluate(() => scrollY) - before)).toBeLessThan(3);
    await page.screenshot({ path: testInfo.outputPath('rich-reader-desktop.png') });
    await page.keyboard.press('Escape');
    await expect(row.locator('.reference-card')).toBeHidden();
    await expect(citation).toBeFocused();

    const marker = block.locator('[data-language="source"] a[data-footnote-target]');
    const target = await marker.getAttribute('data-footnote-target');
    await marker.click();
    const side = row.locator(`[data-note-target="${target}"]`);
    await expect(side).toBeInViewport();
    await side.locator('a.reference-source').click();
    await expect(page.locator(`.footnotes #b-${target}`)).toBeInViewport();
    await expect(page.locator('.footnotes .footnote-entry')).toHaveCount(4);
    await expect(page.locator('article > .reader-block > [data-kind="footnote"]')).toHaveCount(0);
    await page.locator(`.footnotes #b-${target} a[aria-label="返回引用位置"]`).first().click();
    await expect(block).toBeInViewport();
    const nested = page.locator('[data-kind="list_item"] a[data-reference-targets]').first();
    await nested.click();
    await expect(nested.locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," reader-block ")][1]').locator('.reference-card')).toBeVisible();

    await page.locator('[data-action="target"]').click();
    await expect(page.locator('header .title-metadata')).toContainText('Jane Smith');
    await expect(side.locator('[data-language="source"]')).toBeHidden();
    await expect(side.locator('[data-language="target"]')).toBeVisible();
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
      await side.scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`rich-reader-mobile-${width}.png`) });
    }
    await page.emulateMedia({ media: 'print' });
    await expect(side).toBeHidden();
    await expect(page.locator(`.footnotes #b-${target}`)).toBeVisible();
    const ids = await page.locator('[id]').evaluateAll(nodes => nodes.map(node => node.id));
    expect(new Set(ids).size).toBe(ids.length);
    expect(errors).toEqual([]);
    expect(outbound).toEqual([]);
  });
}

test('rich references and footnotes remain navigable without JavaScript', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, offline: true, reducedMotion: 'reduce', viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await page.goto(pathToFileURL(resolve(folder, 'single.html')).href);
  const footnote = page.locator('article a[data-footnote-target]').first();
  const noteId = await footnote.getAttribute('data-footnote-target');
  await footnote.click();
  await expect(page.locator(`.footnotes #b-${noteId}`)).toBeInViewport();
  const reference = page.locator('a[data-reference-targets]').first();
  const referenceId = (await reference.getAttribute('data-reference-targets'))!.split(' ')[0];
  await reference.click();
  await expect(page.locator(`#b-${referenceId}`)).toBeInViewport();
  await expect(page.locator('.footnotes .footnote-entry')).toHaveCount(4);
  await context.close();
});
