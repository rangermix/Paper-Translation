import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { inputPath } from './paths';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const supplied = process.env.LIBRARY_READER_SIDENOTES_EVIDENCE;
const folder = supplied ? inputPath(supplied) : '';
test.beforeEach(() => test.skip(!supplied, 'Set LIBRARY_READER_SIDENOTES_EVIDENCE to the generated reader-v8 fixture directory.'));

for (const format of ['single.html', 'bundle/index.html']) {
  test(`${format} shows contextual footnotes and opens references without leaving the block`, async ({ page, context }, testInfo) => {
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
    const block = page.locator('#b-p1');
    const row = block.locator('..');
    const notes = row.locator(':scope > .reader-notes');
    await expect(notes.locator('[data-note-target="fn1"]')).toBeVisible();
    await expect(page.locator('#b-fn1')).toHaveCount(1);
    const link = block.locator('[data-language="source"] a[data-reference-targets]').first();
    await link.scrollIntoViewIfNeeded();
    await link.focus();
    const before = await page.evaluate(() => scrollY);
    await page.keyboard.press('Enter');
    const card = notes.locator('.reference-card');
    await expect(card).toBeVisible();
    await expect(link).toHaveAttribute('aria-expanded', 'true');
    await expect(card).toContainText('Alice Smith');
    await expect(card).toContainText('Another result');
    expect(page.url()).toBe(url);
    expect(Math.abs(await page.evaluate(() => scrollY) - before)).toBeLessThan(3);
    const wide = await row.evaluate(node => {
      const body = node.querySelector('#b-p1')!.getBoundingClientRect();
      const side = node.querySelector('.reader-notes')!.getBoundingClientRect();
      return { right: body.right, left: side.left, top: body.top, sideTop: side.top, width: document.documentElement.scrollWidth };
    });
    expect(wide.left).toBeGreaterThan(wide.right);
    expect(Math.abs(wide.top - wide.sideTop)).toBeLessThan(3);
    expect(wide.width).toBe(1440);
    await page.screenshot({ path: testInfo.outputPath('sidenotes-desktop.png') });
    await page.keyboard.press('Escape');
    await expect(card).toBeHidden();
    await expect(link).toBeFocused();
    await expect(link).toHaveAttribute('aria-expanded', 'false');
    await link.click();
    await card.getByRole('button', { name: '关闭参考文献' }).click();
    await expect(link).toBeFocused();

    // A second citation of the same footnote stays beside its own paragraph.
    const repeated = page.locator('#b-p2').locator('..').locator('[data-note-target="fn1"]');
    await expect(repeated).toBeVisible();
    await page.locator('#b-p2 [data-language="source"] .footnote-link').click();
    await expect(repeated).toBeInViewport();
    for (const bid of ['item2', 'figcap', 'c1']) {
      const child = page.locator(`#b-${bid}`);
      await child.locator('a[data-reference-targets]').first().click();
      const container = child.locator('a[data-reference-targets]').first().locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " reader-block ")][1]');
      await expect(container.locator(':scope > .reader-notes > .reference-card')).toBeVisible();
    }
    // Escape follows keyboard focus when multiple block cards are open.
    await link.click();
    const otherCard = page.locator('#b-item2 .reference-card');
    await page.locator('#b-item2 a[data-reference-targets]').first().click();
    if (!(await otherCard.isVisible())) await page.locator('#b-item2 a[data-reference-targets]').first().click();
    await card.focus();
    await page.keyboard.press('Escape');
    await expect(card).toBeHidden();
    await expect(otherCard).toBeVisible();
    await expect(link).toBeFocused();
    await otherCard.focus();
    await page.keyboard.press('Escape');
    await expect(otherCard).toBeHidden();
    await page.locator('[data-action="target"]').click();
    await expect(notes.locator('.footnote-card [data-language="source"]')).toBeHidden();
    await expect(notes.locator('.footnote-card [data-language="target"]')).toBeVisible();
    await block.locator('[data-language="target"] a[data-reference-targets]').last().click();
    await expect(card).toContainText('A useful result');
    await expect(card).not.toContainText('Another result');
    await page.locator('[data-action="theme"]').click();
    await page.screenshot({ path: testInfo.outputPath('sidenotes-dark.png') });

    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      const compact = await row.evaluate(node => {
        const body = node.querySelector('#b-p1')!.getBoundingClientRect();
        const side = node.querySelector('.reader-notes')!.getBoundingClientRect();
        return { bottom: body.bottom, top: side.top, width: document.documentElement.scrollWidth };
      });
      expect(compact.top).toBeGreaterThanOrEqual(compact.bottom);
      expect(compact.width).toBe(width);
      await card.scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`sidenotes-mobile-${width}.png`) });
    }
    await page.emulateMedia({ media: 'print' });
    await expect(notes.locator('[data-note-target="fn1"]')).toBeVisible();
    const ids = await page.locator('[id]').evaluateAll(nodes => nodes.map(node => node.id));
    expect(new Set(ids).size).toBe(ids.length);
    expect(errors).toEqual([]);
    expect(outbound).toEqual([]);
  });
}

test('footnotes and bibliography remain readable with JavaScript disabled', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, offline: true, viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await page.goto(pathToFileURL(resolve(folder, 'single.html')).href);
  await expect(page.locator('#b-p1').locator('..').locator('[data-note-target="fn1"]')).toBeVisible();
  const link = page.locator('#b-p1 [data-language="source"] a[data-reference-targets]').first();
  await link.click();
  await expect(page).toHaveURL(/#b-ref1$/);
  await expect(page.locator('#b-ref1')).toBeInViewport();
  await expect(page.locator('#b-ref1')).toContainText('A useful result');
  await context.close();
});

test('references extracted into table cells open in the citing margin', async ({ page, context }) => {
  await context.setOffline(true);
  const url = pathToFileURL(resolve(folder, 'table.html')).href;
  await page.goto(url);
  await page.locator('#b-p2 a[data-reference-targets]').first().click();
  const card = page.locator('#b-p2').locator('..').locator('.reference-card');
  await expect(card).toBeVisible();
  await expect(card).toContainText('A bibliography entry extracted into a table.');
  expect(page.url()).toBe(url);
  await expect(card.locator('td')).toHaveCount(0);
});
