import { test, expect } from '../../apps/web/node_modules/@playwright/test/index.mjs';

for (const filter of ['side', 'locale']) test(`changing search ${filter} restarts at the first matching result`, async ({ page }) => {
  const queries: URLSearchParams[] = [];
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/search')) {
      queries.push(url.searchParams);
      return route.fulfill({ json: { items: [], next_cursor: url.searchParams.has('cursor') ? null : 'entry-30' } });
    }
    return route.fulfill({ json: url.pathname.endsWith('/settings/preferences') ? { theme: 'light' } : {} });
  });
  await page.goto('/#/search');
  await page.getByLabel('正文搜索').fill('translation');
  await page.getByRole('button', { name: '搜索正文' }).click();
  await page.getByRole('button', { name: '下一页结果' }).click();
  await expect.poll(() => queries.at(-1)?.get('cursor')).toBe('entry-30');
  if (filter === 'side') await page.getByLabel('搜索范围').selectOption('target');
  else await page.getByRole('combobox', { name: '目标语言筛选' }).selectOption('ja');
  await expect.poll(() => queries.at(-1)?.get(filter)).toBe(filter === 'side' ? 'target' : 'ja');
  expect(queries.at(-1)?.has('cursor')).toBe(false);
});
