import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

test('mobile navigation leaves the drawer open when dirty-editor navigation is cancelled', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const writes: string[] = [];
  await page.route('**/api/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') writes.push(path);
    const values: Record<string, unknown> = {
      '/settings/preferences': { theme: 'light', generation: 1 },
      '/drafts/edit': { id: 'edit', document_id: 'doc', edition_id: 'edition', generation: 1, source_revision_id: 'source', source_hash: 'source-hash', target_locale: 'zh-Hans',
        segments: [{ block_id: 'b1', version: 1, translatable: true, source_text: 'Original', source_inline: [{ type: 'text', text: 'Original' }], target_inline: [{ type: 'text', text: '译文' }], source_hash: 'source-b1', context_hash: 'context', review_status: 'not_reviewed' }] },
      '/documents/doc': { id: 'doc', title: '编辑保护样本', tags: [], generation: 1, lifecycle: 'active', source_revision_id: 'source', editions: [] },
      '/settings/provider': { configured: false, cost_control_enabled: false },
    };
    return route.fulfill({ json: values[path] ?? { items: [] }, headers: { ETag: '"1"' } });
  });
  await page.goto('/#/drafts/edit');
  await page.getByRole('button', { name: '展开全部段落', exact: true }).click();
  const input = page.locator('#segment-b1').getByRole('textbox', { name: '译文段落', exact: true });
  await input.fill('本地修改');
  await page.getByRole('button', { name: '打开菜单' }).click();
  const drawer = page.getByRole('dialog', { name: '主要导航', exact: true });
  await drawer.getByRole('link', { name: '任务中心', exact: true }).click();
  const guard = page.getByRole('dialog', { name: '有未保存的修改', exact: true });
  await expect(guard).toBeVisible();
  await expect(page).toHaveURL(/#\/drafts\/edit$/);
  for (let index = 0; index < 8; index++) {
    await page.keyboard.press('Tab');
    expect(await guard.evaluate(node => node.contains(document.activeElement))).toBe(true);
  }
  await guard.getByRole('button', { name: '继续编辑', exact: true }).click();
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('link', { name: '任务中心', exact: true })).toBeFocused();
  await drawer.getByRole('link', { name: '任务中心', exact: true }).click();
  await guard.getByRole('button', { name: '放弃修改', exact: true }).click();
  await expect(page).toHaveURL(/#\/jobs$/);
  await expect(drawer).not.toBeVisible();
  await expect(page.locator('#main')).toBeFocused();
  expect(writes).toEqual([]);
});

const jobs = Array.from({ length: 60 }, (_, index) => ({
  id: `job_${index + 1}`, title: `论文 ${index + 1}：用于检查任务列表返回位置的较长标题`,
  stage: 'parse', operation: 'parse', status: 'failed', generation: 1, control_epoch: 1,
  error: { code: 'WORKER_FAILED', message: '后台解析暂未完成。' },
  created_at: '2026-10-18T01:00:00Z', actual_model: { kind: 'local', model_id: 'model-a' },
}));

async function setup(page: Page, empty = false) {
  const errors: string[] = [];
  const queries: URLSearchParams[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    const path = url.pathname.slice(7);
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    if (path === '/settings/preferences') return route.fulfill({ json: { theme: 'light', locale: 'zh-Hans', publish_policy: 'auto_publish' } });
    if (path === '/jobs' && !url.searchParams.has('parent_job_id')) {
      queries.push(url.searchParams);
      const offset = url.searchParams.has('cursor') ? 30 : 0;
      return route.fulfill({ json: { items: empty ? [] : jobs.slice(offset, offset + 30), next_cursor: empty || offset ? null : 'page-two' } });
    }
    if (/^\/jobs\/[^/]+$/.test(path)) {
      const job = jobs.find(item => path === `/jobs/${item.id}`);
      return job ? route.fulfill({ json: job }) : route.fulfill({ status: 404, json: { error: { code: 'JOB_NOT_FOUND', message: '任务不存在或已不可访问。' } } });
    }
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
  return { errors, queries };
}

for (const width of [390, 768, 1100]) {
  test(`direct task details are in the first viewport at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const { errors } = await setup(page);
    await page.goto('/#/jobs/job_30');
    const detail = page.getByRole('region', { name: '任务详情', exact: true });
    const title = detail.getByRole('heading', { level: 2 });
    await expect(title).toContainText('论文 30');
    await expect(page.locator('.job-entry')).toHaveCount(30);
    await expect(page.getByRole('region', { name: '后台任务列表' })).toBeHidden();
    await expect(detail.getByRole('link', { name: '返回任务列表' })).toBeInViewport();
    await expect(title).toBeInViewport();
    await expect(detail.locator('.pill').first()).toHaveText('失败');
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
    await page.reload();
    await expect(title).toBeInViewport();
    if (width === 390) await page.screenshot({ path: outputDirectory('mobile-task-detail.png') });
    expect(errors).toEqual([]);
  });
}

test('desktop keeps task list and selected details side by side', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const { errors } = await setup(page);
  await page.goto('/#/jobs/job_30');
  const list = page.getByRole('region', { name: '后台任务列表' });
  const detail = page.getByRole('region', { name: '任务详情', exact: true });
  await expect(detail.getByRole('heading', { level: 2 })).toContainText('论文 30');
  await expect(list).toBeVisible();
  const listBox = await list.boundingBox(), detailBox = await detail.boundingBox();
  expect(detailBox!.x).toBeGreaterThan(listBox!.x + listBox!.width);
  expect(Math.abs(detailBox!.y - listBox!.y)).toBeLessThan(2);
  expect(errors).toEqual([]);
});

test('mobile detail return and browser history preserve filters, page, scroll and focus', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { errors, queries } = await setup(page);
  await page.goto('/#/jobs');
  const list = page.getByRole('region', { name: '后台任务列表' });
  await list.getByRole('searchbox', { name: '搜索任务' }).fill('论文');
  await expect.poll(() => queries.at(-1)?.get('q')).toBe('论文');
  await list.getByRole('checkbox', { name: '显示已清除历史' }).check();
  await list.getByRole('button', { name: '需要处理', exact: true }).click();
  await list.getByLabel('任务类型').selectOption('parse');
  await list.getByLabel('使用的模型').fill('model-a');
  await list.getByRole('button', { name: '下一页', exact: true }).click();
  const row = list.locator('a[href="#/jobs/job_44"]');
  await expect(row).toBeVisible();
  await row.scrollIntoViewIfNeeded();
  const scrollY = await page.evaluate(() => window.scrollY);
  await row.click();
  await expect(page.getByRole('region', { name: '任务详情', exact: true }).getByRole('heading', { level: 2 })).toBeInViewport();
  await expect(list).toBeHidden();

  async function verifyReturn() {
    await expect(row).toBeFocused();
    await expect(list.getByRole('status').last()).toContainText('第 2 页');
    await expect(list.getByRole('searchbox', { name: '搜索任务' })).toHaveValue('论文');
    await expect(list.getByRole('checkbox', { name: '显示已清除历史' })).toBeChecked();
    await expect(list.getByRole('button', { name: '需要处理', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(list.getByLabel('任务类型')).toHaveValue('parse');
    await expect(list.getByLabel('使用的模型')).toHaveValue('model-a');
    await expect.poll(async () => Math.abs(await page.evaluate(() => window.scrollY) - scrollY)).toBeLessThan(2);
  }

  await page.goBack();
  await verifyReturn();
  await page.goForward();
  await expect(page.getByRole('region', { name: '任务详情', exact: true }).getByRole('heading', { level: 2 })).toBeInViewport();
  await page.getByRole('link', { name: '返回任务列表' }).click();
  await verifyReturn();
  expect(queries.at(-1)?.get('cursor')).toBe('page-two');
  expect(errors).toEqual([]);
});

test('missing task has a usable return path even when the list is empty', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { errors } = await setup(page, true);
  await page.goto('/#/jobs/deleted');
  await expect(page.getByRole('alert')).toContainText('任务不存在或已不可访问');
  await expect(page.getByRole('link', { name: '返回任务列表' })).toBeInViewport();
  await page.getByRole('link', { name: '返回任务列表' }).click();
  await expect(page.getByRole('heading', { name: '还没有后台任务' })).toBeVisible();
  await expect(page.getByRole('searchbox', { name: '搜索任务' })).toBeFocused();
  expect(errors).toEqual([]);
});

test('mobile navigation traps focus, isolates background, closes with Escape and restores the trigger', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { errors } = await setup(page);
  await page.goto('/#/jobs');
  const trigger = page.getByRole('button', { name: '打开菜单' });
  const menu = page.getByRole('dialog', { name: '主要导航' });
  await trigger.click();
  await expect(menu.getByRole('button', { name: '关闭菜单' })).toBeFocused();
  expect(await menu.evaluate(element => element.matches(':modal'))).toBe(true);
  await page.locator('.topbar-action').evaluate(element => (element as HTMLElement).focus());
  expect(await menu.evaluate(element => element.contains(document.activeElement))).toBe(true);
  for (const key of ['Tab', 'Shift+Tab']) {
    for (let i = 0; i < 13; i++) {
      await page.keyboard.press(key);
      expect(await menu.evaluate(element => element.contains(document.activeElement))).toBe(true);
    }
  }
  await page.screenshot({ path: outputDirectory('mobile-navigation.png') });
  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('');
  await trigger.click();
  await page.mouse.click(375, 400);
  await expect(menu).toBeHidden();
  await expect(trigger).toBeFocused();
  expect(errors).toEqual([]);
});

test('mobile navigation closes after committed route changes and across desktop breakpoints', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { errors } = await setup(page);
  await page.goto('/#/jobs');
  const trigger = page.getByRole('button', { name: '打开菜单' });
  const menu = page.getByRole('dialog', { name: '主要导航' });
  await trigger.click();
  await menu.getByRole('link', { name: '文档库', exact: true }).click();
  await expect(page).toHaveURL(/#\/library$/);
  await expect(menu).toBeHidden();
  await expect(page.getByRole('main')).toBeFocused();
  await trigger.click();
  await menu.getByRole('link', { name: '文档库', exact: true }).click();
  await expect(menu).toBeHidden();
  await expect(page.getByRole('main')).toBeFocused();
  await trigger.click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(page.getByRole('complementary', { name: '主要导航' })).toBeVisible();
  await expect(page.getByRole('main')).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(menu).toBeHidden();
  await trigger.click();
  await expect(menu.getByRole('button', { name: '关闭菜单' })).toBeFocused();
  await menu.getByRole('button', { name: '关闭菜单' }).click();
  await expect(trigger).toBeFocused();
  expect(errors).toEqual([]);
});
