import { test, expect, type Page } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const jobs = [
  { id: 'job_translation', title: 'Attention Is All You Need', stage: 'translate', status: 'running', target_locale: 'zh-Hans', verified_blocks: 24, total_blocks: 86, created_at: '2026-09-07T05:42:00Z' },
  { id: 'job_scan', title: '分布式系统讲义.pdf', stage: 'parse', status: 'failed', error: { code: 'OCR_REQUIRED', message: '部分正文没有可提取的文本层，需要 OCR。' }, created_at: '2026-09-07T05:37:00Z' },
  { id: 'job_unknown', title: 'Efficiently Scaling Transformer Inference', stage: 'translate', status: 'outcome_unknown', target_locale: 'zh-Hans', verified_blocks: 8, total_blocks: 52, created_at: '2026-09-07T05:28:00Z' },
  { id: 'job_export', title: 'Pathways: Asynchronous Distributed Dataflow for ML', stage: 'export', status: 'succeeded', created_at: '2026-09-07T04:51:00Z' },
  { id: 'job_inspect', title: 'The Illustrated Transformer.pdf', stage: 'inspect', status: 'succeeded', checked_pages: 12, total_pages: 12, created_at: '2026-09-07T04:46:00Z' },
  { id: 'job_queued', title: '论文中的公式、图表与跨页段落：一份较长的文档标题测试.pdf', stage: 'inspect', status: 'pending', created_at: '2026-09-07T04:32:00Z' },
].map(j => ({ ...j, control_epoch: 1, generation: 1 }));

async function setup(page: Page, theme = 'dark') {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const queries: URLSearchParams[] = [];
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url()); const path = url.pathname.slice(7);
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    let json: unknown = { items: [] };
    if (path === '/capabilities') json = { phase: 'M2', source_mime_types: ['application/pdf'] };
    if (path === '/settings/preferences') json = { theme, locale: 'zh-Hans', publish_policy: 'manual_approval' };
    if (path === '/jobs') {
      queries.push(url.searchParams);
      const q = url.searchParams.get('q')?.toLowerCase(); const group = url.searchParams.get('group');
      let items = url.searchParams.has('cursor') ? [{ ...jobs[4], id: 'job_older', title: 'An older PDF.pdf' }] : jobs;
      if (q) items = items.filter(j => j.title.toLowerCase().includes(q));
      if (group === 'attention') items = items.filter(j => ['failed', 'outcome_unknown'].includes(j.status));
      json = { items, next_cursor: !url.searchParams.has('cursor') && !q && !group ? jobs.at(-1)!.id : null };
    }
    if (path.startsWith('/jobs/')) json = jobs.find(j => path.endsWith('/' + j.id)) ?? { items: [] };
    return route.fulfill({ json, headers: { ETag: '"1"' } });
  });
  return { errors, queries };
}

for (const theme of ['dark', 'light']) {
  test(`task center ${theme}: readable names, verified progress and responsive layout`, async ({ page }) => {
    const { errors } = await setup(page, theme);
    await page.goto('/#/jobs');
    await expect(page.getByRole('heading', { name: '任务中心', exact: true })).toBeVisible();
    await expect(page.locator('.job-entry')).toHaveCount(6);
    await expect(page.locator('.job-entry').first()).toContainText('Attention Is All You Need');
    await expect(page.locator('.job-entry').first()).toContainText('全文翻译');
    await expect(page.locator('.job-entry').first()).toContainText('简体中文');
    await expect(page.getByRole('progressbar', { name: '已完成 24 / 86 段' })).toHaveAttribute('value', '24');
    await expect(page.locator('.job-entry').filter({ hasText: 'Pathways:' }).getByRole('progressbar')).toHaveCount(0);
    await expect(page.locator('.job-entries')).not.toContainText('job_');
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    await page.screenshot({ path: outputDirectory(`jobs-${theme}-desktop.png`), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole('searchbox', { name: '搜索任务' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: outputDirectory(`jobs-${theme}-mobile.png`), fullPage: true });
    await page.locator('.job-entry').first().click();
    await expect(page).toHaveURL(/#\/jobs\/job_translation$/);
    await expect(page.getByRole('heading', { name: '全文翻译 · Attention Is All You Need' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByText('任务技术信息', { exact: true }).click();
    await expect(page.locator('.job-technical')).toContainText('job_translation');
    expect(errors).toEqual([]);
  });
}

test('search, status filtering and pagination send server queries and update visible results', async ({ page }) => {
  const { queries, errors } = await setup(page);
  await page.goto('/#/jobs');
  await page.getByRole('button', { name: '下一页' }).click();
  await expect(page.locator('.job-entry')).toHaveCount(1);
  await expect(page.locator('.job-entry')).toContainText('An older PDF.pdf');
  expect(queries.at(-1)?.get('cursor')).toBe('job_queued');
  await page.getByRole('button', { name: '上一页' }).click();
  await expect(page.locator('.job-entry')).toHaveCount(6);
  await page.getByRole('button', { name: '需要处理', exact: true }).click();
  await expect(page.locator('.job-entry')).toHaveCount(2);
  expect(queries.at(-1)?.get('group')).toBe('attention');
  await page.getByRole('searchbox', { name: '搜索任务' }).fill('Scaling');
  await expect(page.locator('.job-entry')).toHaveCount(1);
  expect(queries.at(-1)?.get('q')).toBe('Scaling');
  expect(queries.at(-1)?.has('cursor')).toBe(false);
  await page.screenshot({ path: outputDirectory('jobs-filtered.png'), fullPage: true });
  await page.locator('.job-entry').click();
  await expect(page.getByRole('heading', { name: '全文翻译 · Efficiently Scaling Transformer Inference' })).toBeVisible();
  await expect(page.getByRole('button', { name: '恢复安全缺失单元' })).toHaveCount(0);
  await expect(page.getByText('请求结果未知，可能已经计费', { exact: true })).toBeVisible();
  await page.getByRole('searchbox', { name: '搜索任务' }).fill('no matching PDF');
  await expect(page.getByRole('heading', { name: '没有匹配的任务' })).toBeVisible();
  await page.getByRole('button', { name: '清除筛选' }).click();
  await expect(page.locator('.job-entry')).toHaveCount(6);
  await expect(page.getByRole('searchbox', { name: '搜索任务' })).toHaveValue('');
  expect(errors).toEqual([]);
});
