import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const recentKey = 'paper-translation:recent-languages:v1';
async function setup(page: Page, locale = 'zh-Hans', theme = 'light') {
  const writes: string[] = [];
  await page.route('**/api/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') writes.push(path);
    const values: Record<string, unknown> = {
      '/capabilities': { source_mime_types: ['application/pdf'] },
      '/settings/preferences': { generation: 1, locale, theme },
      '/settings/provider': { configured: false }, '/settings/dispatch': { generation: 1, dispatch_disabled: false },
    };
    return route.fulfill({ json: values[path] ?? { items: [] }, headers: { ETag: '"1"' } });
  });
  await page.goto('/#/upload');
  await expect(page.getByLabel('翻译为', { exact: true })).toHaveValue(locale);
  return writes;
}

async function openSearch(page: Page) {
  await page.getByRole('button', { name: '查找语言', exact: true }).click();
  const panel = page.getByRole('region', { name: '翻译为：查找语言', exact: true });
  const search = panel.getByRole('combobox', { name: '搜索语言名称或代码', exact: true });
  await expect(search).toBeFocused();
  return { panel, search };
}

test('language search supports localized, native and locale queries and preserves script variants with keyboard selection', async ({ page }) => {
  const writes = await setup(page);
  let { panel, search } = await openSearch(page);
  await search.fill('日语');
  await expect(panel.getByRole('option')).toHaveCount(1);
  await expect(panel.getByRole('option')).toContainText('日本語');
  await search.fill('Deutsch');
  await search.press('Enter');
  await expect(page.getByLabel('翻译为', { exact: true })).toHaveValue('de');
  ({ panel, search } = await openSearch(page));
  await search.fill('zh-H');
  await expect(panel.getByRole('option')).toHaveCount(2);
  await search.press('ArrowDown');
  await expect(panel.getByRole('option', { selected: true })).toContainText('zh-Hant');
  await search.press('Enter');
  await expect(page.getByLabel('翻译为', { exact: true })).toHaveValue('zh-Hant');
  ({ panel, search } = await openSearch(page));
  await search.fill('pt-br');
  await panel.getByRole('option').click();
  await expect(page.getByLabel('翻译为', { exact: true })).toHaveValue('pt-BR');
  expect(writes).toEqual([]);
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), recentKey)).toEqual(['pt-BR', 'zh-Hant', 'de']);
});

test('no results and Escape preserve the current language; recent choices remain unique after reload', async ({ page }) => {
  const writes = await setup(page);
  await page.getByLabel('翻译为', { exact: true }).selectOption('ja');
  const { panel, search } = await openSearch(page);
  await search.fill('没有这种语言');
  await expect(panel.getByRole('status')).toContainText('没有匹配语言');
  await expect(panel.getByRole('option')).toHaveCount(0);
  await search.press('Enter');
  await expect(page.getByLabel('翻译为', { exact: true })).toHaveValue('ja');
  await search.press('Escape');
  await expect(panel).toHaveCount(0);
  await expect(page.getByRole('button', { name: '查找语言', exact: true })).toBeFocused();
  await page.reload();
  const select = page.getByLabel('翻译为', { exact: true });
  await expect(select).toHaveValue('zh-Hans');
  await expect(select.locator('optgroup[label="最近使用"] option[value="ja"]')).toHaveCount(1);
  await expect(select.locator('option[value="ja"]')).toHaveCount(1);
  expect(writes).toEqual([]);
});

test('historical and custom locale identifiers keep every script, region and extension', async ({ page }) => {
  await page.addInitScript(key => localStorage.setItem(key, '{invalid'), recentKey);
  await setup(page, 'sr-Latn-RS');
  const select = page.getByLabel('翻译为', { exact: true });
  await expect(select.locator('option[value="sr-Latn-RS"]')).toHaveCount(1);
  const { panel, search } = await openSearch(page);
  await search.fill('sr-Latn-RS');
  await expect(panel.getByRole('option')).toHaveCount(1);
  await search.press('Enter');
  await expect(select).toHaveValue('sr-Latn-RS');
  await select.selectOption('__custom');
  await page.getByLabel('语言代码（如 fil、pt-BR）', { exact: true }).fill('en-US-u-ca-gregory');
  await page.getByRole('heading', { name: '上传 PDF', exact: true }).click();
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), recentKey)).toEqual(['en-US-u-ca-gregory', 'sr-Latn-RS']);
  await page.getByRole('button', { name: '查找语言', exact: true }).click();
  await page.getByRole('combobox', { name: '搜索语言名称或代码', exact: true }).fill('en-US-u-ca-gregory');
  await page.getByRole('region', { name: '翻译为：查找语言' }).getByRole('option').click();
  await expect(select).toHaveValue('en-US-u-ca-gregory');
});

for (const theme of ['light', 'dark']) test(`language results fit a 320px screen with long names in ${theme} theme`, async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await setup(page, 'en-US-u-ca-gregory', theme);
  const { panel, search } = await openSearch(page);
  await search.fill('en-US');
  await expect(panel.getByRole('option')).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320);
  const box = await panel.getByRole('option').boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(48);
  await page.screenshot({ path: outputDirectory(`language-picker-${theme}-320.png`), fullPage: true });
});
