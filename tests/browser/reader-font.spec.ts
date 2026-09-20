import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { inputPath } from './paths';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const supplied = process.env.LIBRARY_READER_FONT_EVIDENCE;
const folder = supplied ? inputPath(supplied) : '';
test.beforeEach(() => test.skip(!supplied, 'Set LIBRARY_READER_FONT_EVIDENCE to the generated reader-v7 fixture directory.'));

const namedFonts = [
  ['方正宋体', 'fz-song', 'FZShuSong-Z01'],
  ['方正黑体', 'fz-hei', 'FZHei-B01'],
  ['思源宋体', 'source-han-serif', 'Source Han Serif SC'],
  ['思源黑体', 'source-han-sans', 'Source Han Sans SC'],
  ['MiSans', 'misans', 'MiSans'],
  ['鸿蒙黑体', 'harmonyos-sans', 'HarmonyOS Sans SC'],
  ['Noto Sans Simplified Chinese', 'noto-sans-sc', 'Noto Sans SC'],
];

for (const format of ['single.html', 'bundle/index.html']) {
  test(`${format} preserves each named font choice with offline fallbacks`, async ({ page, context }, testInfo) => {
    const outbound: string[] = [], errors: string[] = [];
    page.on('request', request => { if (/^https?:/.test(request.url())) outbound.push(request.url()); });
    page.on('pageerror', error => errors.push(error.message));
    await context.setOffline(true);
    await page.goto(pathToFileURL(resolve(folder, format)).href);
    const select = page.getByRole('combobox', { name: '字体', exact: true });
    await expect(select.locator('option')).toHaveText(['默认', '衬线', '无衬线', '等宽', ...namedFonts.map(([label]) => label)]);
    const source = page.locator('#b-p1 .para.en'), target = page.locator('#b-p1 .para.zh');
    const code = page.locator('#b-code code').first();
    const codeFont = await code.evaluate(node => getComputedStyle(node).fontFamily);
    for (const [label, value, family] of namedFonts) {
      await select.selectOption({ label });
      await page.reload();
      await expect(select).toHaveValue(value);
      await expect(select).toHaveAttribute('title', `${label} · 使用本机字体；未安装时使用备用字体。`);
      const selectedFamily = await source.evaluate(node => getComputedStyle(node).fontFamily);
      expect(selectedFamily).toContain(family);
      await expect(target).toHaveCSS('font-family', selectedFamily);
      await expect(code).toHaveCSS('font-family', codeFont);
      await expect(source).toBeVisible();
      await expect(target).toBeVisible();
    }
    await page.screenshot({ path: testInfo.outputPath('named-font-desktop.png') });
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      const geometry = await page.getByRole('group', { name: '字体与字号' }).evaluate(group => {
        const controls = Array.from(group.querySelectorAll('select, button')).map(node => {
          const box = node.getBoundingClientRect();
          return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
        });
        return { width: innerWidth, scrollWidth: document.documentElement.scrollWidth, controls };
      });
      expect(geometry.scrollWidth).toBe(width);
      expect(geometry.controls.every(box => box.left >= 0 && box.right <= width)).toBe(true);
      expect(Math.max(...geometry.controls.map(box => box.top))).toBeLessThan(Math.min(...geometry.controls.map(box => box.bottom)));
      await expect(select).toHaveValue('noto-sans-sc');
      await page.screenshot({ path: testInfo.outputPath(`named-font-mobile-${width}.png`) });
    }
    expect(errors).toEqual([]);
    expect(outbound).toEqual([]);
  });

  test(`${format} switches both reading languages and remembers the font offline`, async ({ page, context }, testInfo) => {
    const errors: string[] = [], outbound: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    page.on('request', request => { if (/^https?:/.test(request.url())) outbound.push(request.url()); });
    await context.setOffline(true);
    const url = pathToFileURL(resolve(folder, format)).href;
    await page.goto(url);
    expect(page.url()).toBe(url);
    expect(await page.title()).not.toBe('');
    await expect(page.locator('article')).toBeVisible();
    const select = page.getByRole('combobox', { name: '字体', exact: true });
    await expect(select).toBeVisible();
    await expect(select).toHaveValue('default');
    const source = page.locator('#b-p1 .para.en');
    const target = page.locator('#b-p1 .para.zh');
    const font = (locator: typeof source) => locator.evaluate(node => getComputedStyle(node).fontFamily);
    const original = [await font(source), await font(target)];
    const code = page.locator('#b-code code').first();
    const codeFont = await font(code);
    for (const [value, expected] of [['serif', 'Georgia'], ['sans', 'sans-serif'], ['monospace', 'monospace']]) {
      await select.selectOption(value);
      expect(await font(source)).toContain(expected);
      expect(await font(target)).toBe(await font(source));
      expect(await font(code)).toBe(codeFont);
    }
    await select.selectOption('default');
    expect([await font(source), await font(target)]).toEqual(original);
    await select.selectOption('sans');
    await page.reload();
    await expect(select).toHaveValue('sans');
    expect(await font(source)).toContain('sans-serif');
    expect(await font(target)).toBe(await font(source));
    const size = () => source.evaluate(node => parseFloat(getComputedStyle(node).fontSize));
    const before = await size();
    await page.getByRole('button', { name: '增大字号', exact: true }).click();
    expect(await size()).toBe(before + 2);
    await page.getByRole('button', { name: '减小字号', exact: true }).click();
    expect(await size()).toBe(before);
    await select.focus();
    await expect(select).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: '减小字号', exact: true })).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath('font-desktop.png') });
    await page.getByRole('button', { name: '切换主题', exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      const boxes = await page.getByRole('group', { name: '字体与字号' }).evaluate(group => {
        const controls = Array.from(group.querySelectorAll('select, button')).map(node => {
          const box = node.getBoundingClientRect();
          return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
        });
        return { controls, width: innerWidth, scrollWidth: document.documentElement.scrollWidth };
      });
      expect(boxes.scrollWidth).toBe(width);
      expect(boxes.controls).toHaveLength(3);
      expect(boxes.controls.every(box => box.left >= 0 && box.right <= boxes.width)).toBe(true);
      expect(Math.max(...boxes.controls.map(box => box.top))).toBeLessThan(Math.min(...boxes.controls.map(box => box.bottom)));
      await select.selectOption('serif');
      expect(await font(target)).toContain('Georgia');
      await page.screenshot({ path: testInfo.outputPath(`font-mobile-${width}.png`) });
    }
    expect(errors).toEqual([]);
    expect(outbound).toEqual([]);
  });

  test(`${format} handles invalid preferences and unavailable browser storage`, async ({ page, context }) => {
    const url = pathToFileURL(resolve(folder, format)).href;
    await context.setOffline(true);
    await page.goto(url);
    const select = page.getByRole('combobox', { name: '字体', exact: true });
    await page.evaluate(() => localStorage.setItem('reader-v7:font', 'unknown-font'));
    await page.reload();
    await expect(select).toHaveValue('default');
    await context.addInitScript(() => {
      Object.defineProperty(window, 'localStorage', { get() { throw new Error('Storage unavailable'); } });
    });
    await page.reload();
    await expect(page.locator('#reader-storage-notice')).toBeVisible();
    await select.selectOption('monospace');
    await expect(page.locator('#b-p1 .para.zh')).toHaveCSS('font-family', /monospace/);
    await page.getByRole('button', { name: '原文', exact: true }).click();
    await expect(page.locator('#b-p1 .para.zh')).toBeHidden();
    await expect(page.locator('#b-p1 .para.en')).toBeVisible();
  });
}
