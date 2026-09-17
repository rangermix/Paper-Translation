import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const job = { id: 'job_logs', title: 'Attention Is All You Need', stage: 'parse', status: 'succeeded', generation: 1, control_epoch: 1,
  created_at: '2026-09-15T01:00:00Z', started_at: '2026-09-15T01:00:01Z', finished_at: '2026-09-15T01:02:01Z',
  queue_ms: 1000, execution_ms: 120000, actual_model: { kind: 'none' }, config_snapshot: { operation: 'parse' } };
const entries = Array.from({ length: 112 }, (_, index) => ({
  sequence: index + 1, at: '2026-09-15T01:01:00Z', level: index % 3 === 0 ? 'warning' : 'info',
  stage: index % 2 === 0 ? 'parse' : 'quality_check', operation: 'page_processed', page: index + 1,
  message: `记录 ${index + 1}：已完成页面解析，公式、表格与代码保留原 PDF 对照，详细信息可展开查看。`,
  details: { note: `页面 ${index + 1} 的完整执行详情`, unit_id: 'unit_' + 'a'.repeat(180) },
}));

async function setup(page: Page, theme = 'light') {
  const errors: string[] = [], queries: URLSearchParams[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (['error', 'warning'].includes(message.type())) errors.push(message.text()); });
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url()), path = url.pathname.slice(7);
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    let json: unknown = { items: [] };
    if (path === '/capabilities') json = { phase: 'M2', source_mime_types: ['application/pdf'] };
    if (path === '/settings/preferences') json = { theme, locale: 'zh-Hans', publish_policy: 'manual_approval' };
    if (path === '/jobs') json = { items: [job], next_cursor: null };
    if (path === '/jobs/job_logs') json = job;
    if (path === '/jobs/job_logs/logs') {
      queries.push(url.searchParams);
      const limit = Number(url.searchParams.get('limit') ?? 50), cursor = Number(url.searchParams.get('cursor') ?? 0);
      const rows = entries.filter(entry => entry.sequence > cursor
        && (!url.searchParams.get('level') || entry.level === url.searchParams.get('level'))
        && (!url.searchParams.get('stage') || entry.stage === url.searchParams.get('stage')));
      json = { items: rows.slice(0, limit), next_cursor: rows.length > limit ? rows[limit - 1].sequence : null };
    }
    return route.fulfill({ json, headers: { ETag: '"1"' } });
  });
  await page.goto('/#/jobs/job_logs');
  await expect(page).toHaveTitle(/对照文库/);
  await expect(page.getByRole('heading', { name: '解析原文 · Attention Is All You Need' })).toBeVisible();
  return { errors, queries };
}

for (const theme of ['light', 'dark']) {
  test(`task logs ${theme}: compact rows expand by click and keyboard on desktop and mobile`, async ({ page }) => {
    const { errors } = await setup(page, theme);
    const logs = page.locator('.task-logs');
    await expect(logs.locator('li')).toHaveCount(50);
    await expect(page.getByRole('link', { name: '下载全部脱敏日志' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '复制本页' })).toHaveCount(0);
    const row = logs.locator('li').first();
    await expect(row.locator('pre')).toBeHidden();
    await row.locator('summary').click();
    await expect(row.locator('pre')).toBeVisible();
    await expect(row.locator('pre')).toContainText('页面 1 的完整执行详情');
    await row.locator('summary').press('Enter');
    await expect(row.locator('pre')).toBeHidden();
    await page.getByRole('combobox', { name: '每页日志' }).selectOption('10');
    await expect(logs.locator('li')).toHaveCount(10);
    await page.getByRole('heading', { name: '任务日志', exact: true }).evaluate(element => element.scrollIntoView({ block: 'start' }));
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    await page.screenshot({ path: outputDirectory(`job-logs-${theme}-desktop.png`) });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('heading', { name: '任务日志', exact: true }).evaluate(element => element.scrollIntoView({ block: 'start' }));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: outputDirectory(`job-logs-${theme}-mobile.png`) });
    await row.locator('summary').click();
    await expect(row.locator('pre')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: outputDirectory(`job-logs-${theme}-mobile-expanded.png`) });
    expect(errors).toEqual([]);
  });
}

test('log page sizes and filters reset cursors and keep page contents consistent', async ({ page }) => {
  const { errors, queries } = await setup(page);
  const rows = page.locator('.task-logs > li');
  const size = page.getByRole('combobox', { name: '每页日志' });
  const previous = page.getByRole('button', { name: '上一页日志' });
  const next = page.getByRole('button', { name: '下一页日志' });
  await size.selectOption('10');
  await expect(rows).toHaveCount(10);
  await expect(previous).toBeDisabled();
  await next.click();
  await expect(rows.first()).toContainText('记录 11：');
  await expect(page.getByText('第 2 页', { exact: true })).toBeVisible();
  await previous.click();
  await expect(rows.first()).toContainText('记录 1：');
  await next.click();
  await expect(rows.first()).toContainText('记录 11：');
  await size.selectOption('100');
  await expect(rows).toHaveCount(100);
  await expect(rows.first()).toContainText('记录 1：');
  await expect(previous).toBeDisabled();
  expect(queries.at(-1)?.has('cursor')).toBe(false);
  await next.click();
  await expect(rows).toHaveCount(12);
  await expect(rows.first()).toContainText('记录 101：');
  await expect(next).toBeDisabled();
  await size.selectOption('25');
  await expect(rows).toHaveCount(25);
  await next.click();
  await expect(rows.first()).toContainText('记录 26：');
  await page.getByRole('combobox', { name: '等级', exact: true }).selectOption('warning');
  await expect(rows.first()).toContainText('记录 1：');
  await expect(previous).toBeDisabled();
  expect(queries.at(-1)?.has('cursor')).toBe(false);
  expect(queries.at(-1)?.get('limit')).toBe('25');
  await page.getByRole('combobox', { name: '阶段', exact: true }).selectOption('quality_check');
  await expect(rows).toHaveCount(19);
  await expect(rows.first()).toContainText('记录 4：');
  await expect(next).toBeDisabled();
  await page.getByRole('combobox', { name: '等级', exact: true }).selectOption('error');
  await expect(page.getByText('此筛选下暂无日志。')).toBeVisible();
  await expect(page.getByRole('combobox', { name: '阶段', exact: true })).toHaveValue('quality_check');
  await expect(previous).toBeDisabled();
  await expect(next).toBeDisabled();
  expect(errors).toEqual([]);
});
