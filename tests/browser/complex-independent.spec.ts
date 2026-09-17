import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { inputPath } from './paths';
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const supplied = process.env.LIBRARY_COMPLEX_EVIDENCE;
const root = resolve(import.meta.dirname, '../..');
const normalize = (text: string) => text.replace(/\s+/g, ' ').trim();

for (const template of ['reader-v1', 'reader-v2']) for (const format of ['single', 'zip']) {
  test(`independent authored complex source stays complete in ${template} ${format} at 320px`, async ({ page, context }, testInfo) => {
    test.skip(!supplied, 'Requires the final authored M0 export evidence, not a parser gold.');
    const folder = inputPath(supplied!);
    const manifest = JSON.parse(await readFile(resolve(root, 'fixtures/complex-reader/authored-source-manifest.json'), 'utf8'));
    const file = resolve(folder, format === 'single' ? `${template}.html` : `${template}-extracted/index.html`);
    const errors: string[] = [], network: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (/^https?:/.test(request.url())) network.push(request.url()); });
    await context.setOffline(true);
    await page.setViewportSize({ width: 320, height: 900 });
    await page.goto(pathToFileURL(file).href);
    await page.getByRole('button', { name: '双语', exact: true }).click();
    for (const [id, raw] of Object.entries(manifest.blocks)) {
      const block = raw as { source_text: string; target_text: string | null };
      const element = page.locator(`[data-block-id="${id}"]`);
      await expect(element).toHaveCount(1);
      if (block.source_text) {
        const source = element.locator('[data-language="source"]');
        const text = await (await source.count() ? source : element.locator('code')).first().evaluate(node => {
          const copy = node.cloneNode(true) as HTMLElement;
          copy.querySelectorAll('.label').forEach(label => label.remove());
          return copy.textContent ?? '';
        });
        expect(normalize(text), `source block ${id}`).toBe(normalize(block.source_text));
      }
      if (block.target_text) {
        const text = await element.locator('[data-language="target"]').first().evaluate(node => {
          const copy = node.cloneNode(true) as HTMLElement;
          copy.querySelectorAll('.label').forEach(label => label.remove());
          return copy.textContent ?? '';
        });
        expect(normalize(text), `target block ${id}`).toBe(normalize(block.target_text));
      }
    }
    await expect(page.locator('#b-regular-table tr')).toHaveCount(2);
    await expect(page.locator('#b-regular-table td')).toHaveCount(4);
    await expect(page.locator('#b-merged-table tr')).toHaveCount(3);
    await expect(page.locator('#b-merged-table td[rowspan="2"]')).toHaveCount(1);
    await expect(page.locator('#b-merged-table td[colspan="2"]')).toHaveCount(1);
    await expect(page.locator('.toc > ol > li')).toHaveCount(2);
    await expect(page.locator('.toc > ol > li').first().locator('ol > li')).toHaveCount(1);
    await expect(page.locator('#b-deep-code h4')).toBeVisible();
    expect(await page.locator('#b-long-code code').textContent()).toBe(manifest.blocks['long-code'].source_text);
    const dimensions = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth }));
    expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
    const prefix = testInfo.outputPath(`independent-${template}-${format}`);
    await page.screenshot({ path: `${prefix}-320.png`, fullPage: true });
    await page.locator('#b-merged-table').screenshot({ path: `${prefix}-merged-table.png` });
    await page.locator('#b-long-code').screenshot({ path: `${prefix}-code.png` });
    const code = await page.locator('#b-long-code pre').evaluate(node => {
      node.scrollLeft = node.scrollWidth;
      return { client: node.clientWidth, content: node.scrollWidth, reached: node.scrollLeft };
    });
    expect(code.content).toBeGreaterThan(code.client);
    expect(code.reached).toBeGreaterThan(0);
    await page.getByRole('link', { name: 'authored note', exact: true }).click();
    await expect(page).toHaveURL(/#b-footnote$/);
    await page.getByRole('link', { name: '返回引用位置', exact: true }).click();
    await expect(page).toHaveURL(/#b-note-reference$/);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({ path: `${prefix}-desktop.png`, fullPage: true });
    expect(errors).toEqual([]);
    expect(network).toEqual([]);
    await writeFile(`${prefix}-facts.json`, JSON.stringify({ reviewer: '/root/web_ui', scope: 'authored M0 fixture only', file, blocks: Object.keys(manifest.blocks).length, exact_source_target_text: true, table_grids_and_spans: true, nested_toc: true, exact_code_and_local_scroll: code, footnote_roundtrip: true, viewport320: dimensions, errors, network }, null, 2));
  });
}
