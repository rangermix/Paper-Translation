import { test, expect, type Page } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

async function setup(page: Page, options: { count?: number; fail?: boolean; delay?: boolean } = {}) {
  let cleared = false;
  const writes: { body: unknown; etag?: string; key?: string }[] = [];
  const errors: string[] = [];
  const queries: URLSearchParams[] = [];
  let releaseClear = () => {};
  const pendingClear = new Promise<void>(resolve => { releaseClear = resolve; });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.slice(7);
    let json: unknown = { items: [] };
    if (path === '/capabilities') json = { phase: 'M2', source_mime_types: ['application/pdf'] };
    if (path === '/settings/preferences') json = { theme: 'light', locale: 'zh-Hans' };
    if (path === '/jobs/history') json = { generation: 7, clearable_count: cleared ? 0 : options.count ?? 2 };
    if (path === '/jobs/history/clear') {
      writes.push({ body: request.postDataJSON(), etag: request.headers()['if-match'], key: request.headers()['idempotency-key'] });
      if (options.delay) await pendingClear;
      if (options.fail) return route.fulfill({ status: 412, json: { error: { code: 'PRECONDITION_FAILED', message: '记录已更新，请刷新后重试。' } } });
      cleared = true;
      json = { generation: 8, cleared_count: options.count ?? 2 };
    }
    if (path === '/jobs') {
      queries.push(url.searchParams);
      const running = { id: 'job_running', title: '正在解析的论文.pdf', stage: 'parse', status: 'running', generation: 1 };
      const done = { id: 'job_done', title: '已完成的论文.pdf', stage: 'parse', status: 'succeeded', generation: 1 };
      const older = { ...done, id: 'job_older', title: '较早完成的论文.pdf' };
      let items = [running, ...(!cleared || url.searchParams.get('include_cleared') === 'true' ? [done] : [])];
      if (url.searchParams.has('cursor')) items = [older];
      if (url.searchParams.get('group') === 'completed') items = items.filter(j => j.status === 'succeeded');
      if (url.searchParams.get('q')) items = items.filter(j => j.title.includes(url.searchParams.get('q')!));
      json = { items, next_cursor: !cleared && !url.searchParams.has('cursor') ? 'job_done' : null };
    }
    return route.fulfill({ json, headers: { ETag: '"7"' } });
  });
  return { writes, errors, queries, releaseClear };
}

for (const width of [1440, 390]) {
  test(`clear finished history, retain running jobs and show cleared records at ${width}px`, async ({ page }) => {
    const { writes, errors, releaseClear } = await setup(page, { delay: true });
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1060 });
    await page.goto('/#/jobs');
    await expect(page.getByRole('heading', { name: '任务中心', exact: true })).toBeVisible();
    await expect(page.locator('.job-entry')).toHaveCount(2);
    await page.getByRole('button', { name: '清除已结束任务' }).click();
    const dialog = page.getByRole('dialog', { name: '清除任务历史' });
    await expect(dialog).toContainText('2');
    await expect(dialog).toContainText('所有筛选和分页');
    await expect(dialog).toContainText('文档、译文、日志和费用记录会保留');
    await page.screenshot({ path: outputDirectory(`clear-history-confirm-${width}.png`), fullPage: true });
    await dialog.getByRole('button', { name: '暂不清除' }).click();
    expect(writes).toHaveLength(0);
    await page.getByRole('button', { name: '清除已结束任务' }).click();
    await dialog.getByRole('button', { name: '确认清除' }).click();
    await expect(dialog.getByRole('button', { name: '正在清除…' })).toBeDisabled();
    await expect(dialog.getByRole('button', { name: '暂不清除' })).toBeDisabled();
    await expect(dialog.getByRole('button', { name: '关闭', exact: true })).toBeDisabled();
    await page.keyboard.press('Escape');
    await expect(dialog).toBeVisible();
    releaseClear();
    await expect(dialog).not.toBeVisible();
    await expect(page.getByText('已清除 2 项已结束任务。')).toBeVisible();
    await expect(page.locator('.job-entry')).toHaveCount(1);
    await expect(page.locator('.job-entry')).toContainText('正在解析');
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({ body: { confirm: true }, etag: '"7"' });
    expect(writes[0].key).toBeTruthy();
    await page.reload();
    await expect(page.locator('.job-entry')).toHaveCount(1);
    await page.getByRole('checkbox', { name: '显示已清除历史' }).check();
    await expect(page.locator('.job-entry')).toHaveCount(2);
    await page.getByRole('checkbox', { name: '显示已清除历史' }).uncheck();
    await expect(page.locator('.job-entry')).toHaveCount(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    await page.screenshot({ path: outputDirectory(`clear-history-after-${width}.png`), fullPage: true });
    expect(errors).toEqual([]);
  });
}

test('clear spans filters and pages and returns to the unfiltered first page', async ({ page }) => {
  const { queries } = await setup(page);
  await page.goto('/#/jobs');
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.locator('.job-entry')).toHaveCount(1);
  await expect(page.locator('.job-entry')).toContainText('较早完成');
  await page.getByRole('button', { name: '清除已结束任务' }).click();
  await page.getByRole('button', { name: '确认清除' }).click();
  await expect(page.locator('.job-entry')).toContainText('正在解析');
  expect(queries.at(-1)?.has('cursor')).toBe(false);
  await expect(page.getByRole('checkbox', { name: '显示已清除历史' })).not.toBeChecked();
});

test('nothing to clear disables confirmation and preserves the list', async ({ page }) => {
  const { writes } = await setup(page, { count: 0 });
  await page.goto('/#/jobs');
  await page.getByRole('button', { name: '清除已结束任务' }).click();
  await expect(page.getByText('暂无可清除的已结束任务。')).toBeVisible();
  await expect(page.getByRole('button', { name: '确认清除' })).toBeDisabled();
  expect(writes).toHaveLength(0);
});

test('clearing a filtered list resets search, status, type and model filters', async ({ page }) => {
  const { queries } = await setup(page);
  await page.goto('/#/jobs');
  await page.getByRole('button', { name: '已完成', exact: true }).click();
  await page.getByRole('searchbox', { name: '搜索任务' }).fill('已完成');
  await page.getByRole('combobox', { name: '任务类型' }).selectOption('parse');
  await page.getByRole('textbox', { name: '实际模型' }).fill('Docling');
  await expect.poll(() => queries.at(-1)?.get('q')).toBe('已完成');
  await page.getByRole('button', { name: '清除已结束任务' }).click();
  await page.getByRole('button', { name: '确认清除' }).click();
  await expect(page.locator('.job-entry')).toHaveCount(1);
  await expect(page.locator('.job-entry')).toContainText('正在解析');
  await expect(page.getByRole('searchbox', { name: '搜索任务' })).toHaveValue('');
  await expect(page.getByRole('combobox', { name: '任务类型' })).toHaveValue('');
  await expect(page.getByRole('textbox', { name: '实际模型' })).toHaveValue('');
  await expect(page.getByRole('button', { name: '全部任务', exact: true })).toHaveAttribute('aria-pressed', 'true');
  expect([...queries.at(-1)!.keys()]).toEqual(['limit']);
});

test('failed clear keeps the dialog and lets the user refresh its preview', async ({ page }) => {
  const { writes } = await setup(page, { fail: true });
  await page.goto('/#/jobs');
  await page.getByRole('button', { name: '清除已结束任务' }).click();
  await page.getByRole('button', { name: '确认清除' }).click();
  const dialog = page.getByRole('dialog', { name: '清除任务历史' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('记录已更新，请刷新后重试。');
  await expect(page.locator('.job-entry')).toHaveCount(2);
  expect(writes).toHaveLength(1);
  await dialog.getByRole('button', { name: '刷新清除范围' }).click();
  await expect(dialog.getByRole('button', { name: '确认清除' })).toBeEnabled();
});
