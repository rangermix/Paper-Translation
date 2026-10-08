import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { inputPath } from './paths';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const supplied = process.env.LIBRARY_READER_THEME_EVIDENCE;
const folder = supplied ? inputPath(supplied) : '';
const server = process.env.LIBRARY_READER_THEME_URL;
test.beforeEach(() => test.skip(!supplied, 'Set LIBRARY_READER_THEME_EVIDENCE to generated reader-v13 fixtures.'));

for (const version of ['3.0', '4.0']) {
  for (const format of ['published/index.html', 'single.html', 'bundle/index.html']) {
    const published = format.startsWith('published/');
    const url = () => published && server ? `${server}/${version}/${format}` : pathToFileURL(resolve(folder, version, format)).href;

    test(`${version} ${format} follows the system live and remembers explicit choices`, async ({ page, context }, testInfo) => {
      const errors: string[] = [], outbound: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (['error', 'warning'].includes(message.type())) errors.push(message.text()); });
      page.on('request', request => { if (/^https?:/.test(request.url()) && !(server && request.url().startsWith(server + '/'))) outbound.push(request.url()); });
      await context.setOffline(!published);
      await page.emulateMedia({ colorScheme: 'dark' });
      await page.goto(url());
      expect(page.url()).toBe(url());
      expect(await page.title()).not.toBe('');
      await expect(page.locator('article')).toBeVisible();
      await expect(page.locator('vite-error-overlay')).toHaveCount(0);
      const select = page.getByRole('combobox', { name: '主题', exact: true });
      const root = page.locator('html');
      await expect(select).toHaveValue('system');
      await expect(root).toHaveCSS('color-scheme', 'dark');
      await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(17, 23, 27)');
      await page.emulateMedia({ colorScheme: 'light' });
      await expect(root).toHaveCSS('color-scheme', 'light');
      await expect(select).toHaveValue('system');
      await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(245, 242, 236)');
      if (format === 'single.html') await page.screenshot({ path: testInfo.outputPath('system-light-desktop.png') });
      await select.selectOption('dark');
      await page.reload();
      await expect(select).toHaveValue('dark');
      await expect(root).toHaveCSS('color-scheme', 'dark');
      await page.emulateMedia({ colorScheme: 'dark' });
      await page.emulateMedia({ colorScheme: 'light' });
      await expect(root).toHaveCSS('color-scheme', 'dark');
      await select.selectOption('light');
      await page.emulateMedia({ colorScheme: 'dark' });
      await page.reload();
      await expect(select).toHaveValue('light');
      await expect(root).toHaveCSS('color-scheme', 'light');
      await select.selectOption('system');
      await page.reload();
      await expect(select).toHaveValue('system');
      await expect(root).toHaveCSS('color-scheme', 'dark');
      await page.emulateMedia({ colorScheme: 'light' });
      await expect(root).toHaveCSS('color-scheme', 'light');
      await page.emulateMedia({ colorScheme: 'dark' });
      await expect(root).toHaveCSS('color-scheme', 'dark');
      await select.focus();
      await expect(select).toBeFocused();
      if (format === 'single.html') await page.screenshot({ path: testInfo.outputPath('system-dark-desktop.png') });
      for (const width of [390, 320]) {
        await page.setViewportSize({ width, height: 844 });
        await expect(select).toBeVisible();
        const geometry = await select.evaluate(node => ({ left: node.getBoundingClientRect().left,
          right: node.getBoundingClientRect().right, scrollWidth: document.documentElement.scrollWidth }));
        expect(geometry.left).toBeGreaterThanOrEqual(0);
        expect(geometry.right).toBeLessThanOrEqual(width);
        expect(geometry.scrollWidth).toBe(width);
        if (format === 'single.html') await page.screenshot({ path: testInfo.outputPath(`system-dark-mobile-${width}.png`) });
      }
      expect(errors).toEqual([]);
      expect(outbound).toEqual([]);
    });

    test(`${version} ${format} preserves existing choices and handles unavailable storage`, async ({ page, context }) => {
      await context.setOffline(!published);
      await page.goto(url());
      const select = page.getByRole('combobox', { name: '主题', exact: true });
      for (const preference of ['light', 'dark', 'invalid']) {
        await page.evaluate(value => localStorage.setItem('reader-v7:theme', value), preference);
        await page.emulateMedia({ colorScheme: preference === 'dark' ? 'light' : 'dark' });
        await page.reload();
        await expect(select).toHaveValue(preference === 'invalid' ? 'system' : preference);
        await expect(page.locator('html')).toHaveCSS('color-scheme', preference === 'light' ? 'light' : 'dark');
      }
      await context.addInitScript(() => {
        Object.defineProperty(window, 'localStorage', { get() { throw new Error('Storage unavailable'); } });
      });
      await page.reload();
      await expect(page.locator('#reader-storage-notice')).toBeVisible();
      await expect(select).toHaveValue('system');
      await select.selectOption('light');
      await expect(page.locator('html')).toHaveCSS('color-scheme', 'light');
      await select.selectOption('system');
      await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark');
      await page.emulateMedia({ colorScheme: 'light' });
      await expect(page.locator('html')).toHaveCSS('color-scheme', 'light');
    });

    test(`${version} ${format} prints light in either dark mode`, async ({ page, context }) => {
      await context.setOffline(!published);
      await page.emulateMedia({ colorScheme: 'dark' });
      await page.goto(url());
      const select = page.getByRole('combobox', { name: '主题', exact: true });
      for (const mode of ['system', 'dark']) {
        await select.selectOption(mode);
        await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark');
        await page.emulateMedia({ media: 'print' });
        await expect(page.locator('html')).toHaveCSS('color-scheme', 'light');
        await expect(page.locator('body')).toHaveCSS('color', 'rgb(29, 37, 44)');
        await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(255, 255, 255)');
        await expect(select).toBeHidden();
        await page.emulateMedia({ media: 'screen' });
      }
    });

    test(`${version} ${format} follows the system without JavaScript`, async ({ browser }) => {
      const context = await browser.newContext({ javaScriptEnabled: false, colorScheme: 'dark', offline: !published });
      try {
        const page = await context.newPage();
        await page.goto(url());
        await expect(page.locator('article')).toBeVisible();
        await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(17, 23, 27)');
        await page.emulateMedia({ colorScheme: 'light' });
        await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(245, 242, 236)');
      } finally { await context.close(); }
    });

    test(`${version} ${format} loads bundled fonts and remembers independent typography`, async ({ page, context }, testInfo) => {
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      await context.setOffline(!published);
      await page.goto(url());
      const bodyFont = page.getByRole('combobox', { name: '字体', exact: true });
      const codeFont = page.getByRole('combobox', { name: '代码字体', exact: true });
      const spacing = page.getByRole('combobox', { name: '行距', exact: true });
      const paragraph = page.locator('article .para.en').first();
      const block = page.locator('article pre').first();
      const inline = page.locator('article .protected[data-kind="code"], article .para code').first();
      await expect(bodyFont).toHaveValue('default');
      await expect(codeFont).toHaveValue('default');
      await expect(spacing).toHaveValue('1.72');
      await expect(paragraph).toHaveCSS('font-family', /^MiSans,/);
      await expect(block).toHaveCSS('font-family', /^"JetBrains Mono",/);
      await expect(inline).toHaveCSS('font-family', /^"JetBrains Mono",/);
      const loaded = await page.evaluate(async () => {
        await document.fonts.ready;
        return Array.from(document.fonts).filter(font => font.status === 'loaded').map(font => font.family);
      });
      expect(loaded).toContain('MiSans');
      expect(loaded).toContain('JetBrains Mono');
      const options = [
        ['fira-code', 'Fira Code'], ['cascadia-code', 'Cascadia Code'],
        ['source-code-pro', 'Source Code Pro'], ['ibm-plex-mono', 'IBM Plex Mono'],
        ['consolas', 'Consolas'], ['menlo', 'Menlo'], ['monospace', 'ui-monospace'],
        ['default', 'JetBrains Mono'],
      ];
      for (const [value, family] of options) {
        await codeFont.selectOption(value);
        expect(await block.evaluate(node => getComputedStyle(node).fontFamily)).toContain(family);
        expect(await inline.evaluate(node => getComputedStyle(node).fontFamily)).toContain(family);
        await expect(paragraph).toHaveCSS('font-family', /^MiSans,/);
      }
      const toolbarHeight = await page.locator('.toolbar').evaluate(node => node.getBoundingClientRect().height);
      const lineRatio = () => paragraph.evaluate(node => parseFloat(getComputedStyle(node).lineHeight) / parseFloat(getComputedStyle(node).fontSize));
      for (const value of ['1.4', '2', '2.4', '1.72']) {
        await spacing.selectOption(value);
        expect(await lineRatio()).toBeCloseTo(Number(value), 2);
        expect(await page.locator('.toolbar').evaluate(node => node.getBoundingClientRect().height)).toBe(toolbarHeight);
      }
      await bodyFont.selectOption('serif');
      await codeFont.selectOption('fira-code');
      await spacing.selectOption('2');
      await page.reload();
      await expect(bodyFont).toHaveValue('serif');
      await expect(codeFont).toHaveValue('fira-code');
      await expect(spacing).toHaveValue('2');
      expect(await lineRatio()).toBeCloseTo(2, 2);
      await bodyFont.selectOption('default');
      await expect(block).toHaveCSS('font-family', /^"Fira Code",/);
      await codeFont.selectOption('default');
      if (format === 'single.html') await page.screenshot({ path: testInfo.outputPath('typography-desktop.png') });
      for (const width of [390, 320]) {
        await page.setViewportSize({ width, height: 844 });
        for (const control of [bodyFont, codeFont, spacing]) {
          const box = await control.boundingBox();
          expect(box).not.toBeNull();
          expect(box!.x).toBeGreaterThanOrEqual(0);
          expect(box!.x + box!.width).toBeLessThanOrEqual(width);
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
        if (format === 'single.html') await page.screenshot({ path: testInfo.outputPath(`typography-mobile-${width}.png`) });
      }
      await page.evaluate(() => {
        localStorage.setItem('reader-v7:code-font', 'invalid');
        localStorage.setItem('reader-v7:line-height', '100');
      });
      await page.reload();
      await expect(codeFont).toHaveValue('default');
      await expect(spacing).toHaveValue('1.72');
      await context.addInitScript(() => {
        Object.defineProperty(window, 'localStorage', { get() { throw new Error('Storage unavailable'); } });
      });
      await page.reload();
      await expect(page.locator('#reader-storage-notice')).toBeVisible();
      await codeFont.selectOption('consolas');
      await spacing.selectOption('2.4');
      await expect(block).toHaveCSS('font-family', /^Consolas,/);
      expect(await lineRatio()).toBeCloseTo(2.4, 2);
      expect(errors).toEqual([]);
    });
  }
}
