import {test, expect} from '../../apps/web/node_modules/@playwright/test/index.mjs';
import {pathToFileURL} from 'node:url';
import {inputPath} from './paths';

const supplied = process.env.ORIGINAL_ONLY_READER_ROOT;
const retained = ['authors', 'affiliation', 'contact', 'refs', 'ref1', 'ref2'];

for (const file of ['reading.html', 'artifact/index.html']) {
  test(`retained original content stays visible offline in all views: ${file}`, async ({page, context}, testInfo) => {
    test.skip(!supplied, 'Requires the isolated original-only workflow artifact.');
    const requests: string[] = [], errors: string[] = [];
    page.on('request', request => { if (/^https?:/.test(request.url())) requests.push(request.url()); });
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await context.setOffline(true);
    await page.goto(pathToFileURL(inputPath(`${supplied}/${file}`)).href);
    await expect(page).toHaveTitle('Publication fixture');
    await expect(page.locator('article')).toContainText('We evaluate the method');
    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height: width === 1440 ? 1060 : 844});
      for (const view of ['译文', '原文', '双语']) {
        await page.getByRole('button', {name: view, exact: true}).click();
        for (const id of retained) {
          const block = page.locator(`[data-block-id="${id}"]`);
          await expect(block.locator('[data-original-only]')).toBeVisible();
          await expect(block.locator('[data-language="target"]')).toHaveCount(0);
          await expect(block).not.toContainText('暂无译文');
        }
        await expect(page.locator('#b-body [data-language="target"]')).toBeVisible({visible: view !== '原文'});
        await expect(page.locator('#b-body [data-language="source"]')).toBeVisible({visible: view !== '译文'});
      }
      await page.getByRole('button', {name: '译文', exact: true}).click();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path: testInfo.outputPath(`original-only-${width}.png`), fullPage: true});
    }
    await expect(page.getByText('Alice Smith¹, Bob Jones² and Carol Lee¹', {exact: false})).toHaveCount(1);
    await page.getByRole('link', {name: '7. References', exact: true}).click();
    await expect(page).toHaveURL(/#b-refs$/);
    await expect(page.locator('#b-refs [data-original-only]')).toBeVisible();
    expect(requests).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('original-only content is readable with JavaScript disabled', async ({browser}) => {
  test.skip(!supplied, 'Requires the isolated original-only workflow artifact.');
  const context = await browser.newContext({javaScriptEnabled: false, offline: true});
  try {
    const page = await context.newPage();
    await page.goto(pathToFileURL(inputPath(`${supplied}/reading.html`)).href);
    for (const id of retained) await expect(page.locator(`#b-${id} [data-original-only]`)).toBeVisible();
    await expect(page.locator('#b-body')).toContainText('We evaluate the method');
  } finally { await context.close(); }
});
