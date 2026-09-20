import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { inputPath } from './paths';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { writeFile } from 'node:fs/promises';

const supplied = process.env.LIBRARY_READER_V5_EVIDENCE;
const folder = supplied ? inputPath(supplied) : '';
test.beforeEach(() => test.skip(!supplied, 'Set LIBRARY_READER_V5_EVIDENCE to the generated reader-v5 fixture directory.'));

for (const format of ['single.html', 'bundle/index.html']) {
  test(`${format} preserves original outline and metadata with accessible reading margins`, async ({ page, context }, testInfo) => {
    const errors: string[] = [], outbound: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    page.on('request', request => { if (/^https?:/.test(request.url())) outbound.push(request.url()); });
    await context.setOffline(true);
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto(pathToFileURL(resolve(folder, format)).href);
    await expect(page.locator('.toc-sections a')).toHaveText(['Abstract', '1 Introduction', '2 Background & Related Work', '2.1 DNN Training']);
    expect(await page.locator('.toc-sections ul').evaluateAll(nodes => nodes.every(node => getComputedStyle(node).listStyleType === 'none'))).toBe(true);
    await expect(page.locator('.hero #b-authors')).toContainText('Alice Smith');
    await expect(page.locator('.hero #b-affiliation')).toContainText('Example University');
    for (const view of ['source', 'target', 'both']) {
      await page.locator(`[data-action="${view}"]`).click();
      await expect(page.locator(`[data-action="${view}"]`)).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator('.hero #b-authors')).toBeVisible();
      await expect(page.locator('.hero #b-affiliation')).toBeVisible();
      if (view === 'target') await expect(page.locator('#b-p1 [data-language="source"]')).toBeHidden();
      else await expect(page.locator('#b-p1 [data-language="source"]')).toBeVisible();
    }
    await expect(page.locator('.reader-list > ol > li')).toHaveCount(2);
    const block = page.locator('#b-p1');
    const margin = block.locator('..').locator(':scope > .reader-notes');
    const warnings = margin.locator('.block-notes');
    const source = margin.locator('.original-comparison');
    await warnings.locator('summary').focus();
    await page.keyboard.press('Enter');
    await expect(warnings).toHaveAttribute('open', '');
    await source.locator('summary').focus();
    await page.keyboard.press('Enter');
    await expect(source.locator('img')).toBeVisible();
    const wide = await block.locator('..').evaluate(row => {
      const main = row.querySelector('#b-p1')!.getBoundingClientRect();
      const notes = row.querySelector('.reader-notes')!.getBoundingClientRect();
      const content = Array.from(row.querySelectorAll('.reader-notes p, .reader-notes img')).map(node => {
        const box = node.getBoundingClientRect();
        return { left: box.left, right: box.right, width: box.width };
      });
      return { main: { left: main.left, right: main.right, width: main.width }, notes: { left: notes.left, right: notes.right }, content, viewport: innerWidth, width: document.documentElement.scrollWidth };
    });
    expect(wide.notes.left).toBeGreaterThan(wide.main.right);
    expect(wide.content.every(box => box.left >= wide.notes.left && box.right <= wide.notes.right)).toBe(true);
    expect(wide.width).toBe(wide.viewport);
    await block.locator('..').scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath('reader-v5-wide-margin.png') });
    await page.locator('.reader-guide > summary').click();
    const overview = await page.locator('.reader-header').evaluate(row => {
      const hero = row.querySelector('.hero')!.getBoundingClientRect();
      const panel = row.querySelector('.issue-panel')!.getBoundingClientRect();
      return { heroRight: hero.right, panelLeft: panel.left };
    });
    expect(overview.panelLeft).toBeGreaterThan(overview.heroRight);
    await page.screenshot({ path: testInfo.outputPath('reader-v5-title-and-overview.png') });
    await page.locator('.reader-guide > summary').click();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(source.locator('img')).toBeVisible();
    const compact = await block.locator('..').evaluate(row => {
      const main = row.querySelector('#b-p1')!.getBoundingClientRect();
      const notes = row.querySelector('.reader-notes')!.getBoundingClientRect();
      return { mainBottom: main.bottom, notesTop: notes.top, width: document.documentElement.scrollWidth, viewport: innerWidth };
    });
    expect(compact.notesTop).toBeGreaterThanOrEqual(compact.mainBottom);
    expect(compact.width).toBe(compact.viewport);
    await block.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath('reader-v5-compact-margin.png') });
    for (let count = 0; count < 6; count++) await page.locator('[data-action="larger"]').click();
    expect(await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--font-size')))).toBe(30);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
    await page.locator('.toc-sections a[href="#b-training"]').click();
    await expect(page).toHaveURL(/#b-training$/);
    await expect(page.locator('#b-training')).toBeInViewport();
    expect(errors).toEqual([]);
    expect(outbound).toEqual([]);
    await writeFile(testInfo.outputPath('reader-v5-geometry.json'), JSON.stringify({ format, wide, overview, compact, errors, outbound }, null, 2));
  });
}

test('reader-v5 original metadata and comparison stay readable without JavaScript', async ({ browser }, testInfo) => {
  const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 }, offline: true });
  const page = await context.newPage();
  await page.goto(pathToFileURL(resolve(folder, 'single.html')).href);
  await expect(page.locator('.hero #b-authors')).toContainText('Alice Smith');
  await expect(page.locator('.reader-list li')).toHaveCount(2);
  const source = page.locator('#b-p1').locator('..').locator('.original-comparison');
  await source.locator('summary').click();
  await expect(source.locator('img')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('reader-v5-no-javascript.png') });
  await context.close();
});
