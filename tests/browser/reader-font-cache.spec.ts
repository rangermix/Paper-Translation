import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { writeFile } from 'node:fs/promises';

const server = process.env.LIBRARY_READER_CACHE_URL;
const first = process.env.LIBRARY_READER_CACHE_FIRST;
const second = process.env.LIBRARY_READER_CACHE_SECOND;

test('published readers reuse font payloads across artifacts, reloads and controls', async ({ page, context }, testInfo) => {
  test.skip(!server || !first || !second, 'Set LIBRARY_READER_CACHE_URL, FIRST and SECOND to two real API reader-v13 artifacts.');
  test.setTimeout(90000);
  // Route interception disables Chromium's HTTP cache. Observe the real network
  // with CDP instead, and keep all pages in the same fresh browser context.
  let phase = 'first';
  const cachedRequests = new Set<string>();
  const fonts: Array<{ id: string; phase: string; url: string; status: number;
    cached: boolean; bytes: number | null; cacheControl: string }> = [];
  const errors: string[] = [];
  const observe = async (target: typeof page, prefix: string) => {
    target.on('pageerror', error => errors.push(error.message));
    target.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    const cdp = await context.newCDPSession(target);
    await cdp.send('Network.enable');
    cdp.on('Network.requestServedFromCache', ({ requestId }) => {
      cachedRequests.add(prefix + requestId);
      for (const entry of fonts) if (entry.id === prefix + requestId) entry.cached = true;
    });
    cdp.on('Network.responseReceived', ({ requestId, response }) => {
      if (!response.url.includes('/reader-assets/fonts/')) return;
      fonts.push({ id: prefix + requestId, phase, url: response.url, status: response.status,
        cached: !!response.fromDiskCache || cachedRequests.has(prefix + requestId), bytes: null,
        cacheControl: String(response.headers['cache-control'] ?? response.headers['Cache-Control'] ?? '') });
    });
    cdp.on('Network.loadingFinished', ({ requestId, encodedDataLength }) => {
      for (const entry of fonts) if (entry.id === prefix + requestId) entry.bytes = encodedDataLength;
    });
  };
  await observe(page, 'first-tab:');
  const loadEveryVariant = async (target = page) => {
    const loaded = await target.evaluate(async () => {
      for (const font of ['400 16px "MiSans"', '700 16px "MiSans"',
        '400 16px "JetBrains Mono"', '700 16px "JetBrains Mono"',
        'italic 400 16px "JetBrains Mono"', 'italic 700 16px "JetBrains Mono"']) {
        await document.fonts.load(font, 'Font cache 字体 const value = 1;');
      }
      await document.fonts.ready;
      return Array.from(document.fonts).filter(font => font.status === 'loaded').length;
    });
    expect(loaded).toBe(6);
    await expect.poll(() => fonts.filter(font => font.phase === phase && font.bytes !== null).length).toBe(6);
  };
  await page.goto(server! + first!);
  await expect(page.locator('article pre').first()).toBeVisible();
  await loadEveryVariant();
  const initial = fonts.filter(font => font.phase === 'first');
  expect(new Set(initial.map(font => font.url)).size).toBe(6);
  expect(initial.every(font => font.status === 200 && !font.cached && font.bytes! > 0)).toBe(true);
  expect(initial.every(font => font.cacheControl === 'public, max-age=31536000, immutable')).toBe(true);

  phase = 'second';
  await page.goto(server! + second!);
  await loadEveryVariant();
  const subsequent = fonts.filter(font => font.phase === 'second');
  expect(subsequent.map(font => font.url).sort()).toEqual(initial.map(font => font.url).sort());
  expect(subsequent.every(font => font.cached && font.bytes === 0)).toBe(true);

  phase = 'reload';
  await page.reload();
  await loadEveryVariant();
  expect(fonts.filter(font => font.phase === 'reload').every(font => font.cached && font.bytes === 0)).toBe(true);

  phase = 'another-tab';
  const anotherTab = await context.newPage();
  await observe(anotherTab, 'second-tab:');
  await anotherTab.goto(server! + second!);
  await loadEveryVariant(anotherTab);
  expect(fonts.filter(font => font.phase === 'another-tab').every(font => font.cached && font.bytes === 0)).toBe(true);
  await anotherTab.close();

  phase = 'controls';
  await page.getByRole('combobox', { name: '主题', exact: true }).selectOption('dark');
  await page.getByRole('combobox', { name: '字体', exact: true }).selectOption('serif');
  await page.getByRole('combobox', { name: '字体', exact: true }).selectOption('default');
  await page.getByRole('combobox', { name: '代码字体', exact: true }).selectOption('monospace');
  await page.getByRole('combobox', { name: '代码字体', exact: true }).selectOption('default');
  await page.getByRole('combobox', { name: '行距', exact: true }).selectOption('2');
  await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark');
  await expect(page.locator('article pre').first()).toHaveCSS('font-family', /^"JetBrains Mono",/);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: testInfo.outputPath('cached-fonts-reader.png') });
  expect(fonts.filter(font => font.phase === 'controls')).toEqual([]);
  expect(errors).toEqual([]);
  await writeFile(testInfo.outputPath('font-cache-network.json'), JSON.stringify({ fonts,
    initialTransferBytes: initial.reduce((total, font) => total + font.bytes!, 0),
    repeatTransferBytes: fonts.filter(font => font.phase !== 'first').reduce((total, font) => total + font.bytes!, 0),
    controls: 'theme, body font, code font and line spacing changed without font requests' }, null, 2));
});
