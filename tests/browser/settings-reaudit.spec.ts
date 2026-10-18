import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

async function setup(page: Page) {
  let prefs = { generation: 1, locale: 'zh-Hans', theme: 'light', parser_profile_revision: 'surya-ocr-2-v1' };
  const writes: { path: string; body: any }[] = [];
  await page.route('**/api/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') {
      writes.push({ path, body: request.postDataJSON() });
      if (path === '/settings/preferences') prefs = { ...prefs, ...request.postDataJSON(), generation: prefs.generation + 1 };
    }
    const values: Record<string, unknown> = {
      '/settings/preferences': prefs,
      '/settings/provider': { generation: 1, configured: true, has_api_key: false, provider: 'openai', api_protocol: 'responses', auth_mode: 'none', endpoint: 'https://synthetic.invalid/v1/responses', model_id: 'test-model' },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false },
      '/settings/parser-models': { models: [] }, '/settings/local-models': { models: [] },
      '/settings/parser-environment': { online: true, default: 'dmr', options: [{ id: 'dmr', profiles: ['surya-ocr-2-v1'] }] },
      '/settings/resources': { waiting_jobs: [], model_references: [] },
      '/documents': { items: [], total: 0 },
    };
    return route.fulfill({ json: values[path] ?? { items: [] }, headers: { ETag: `"${prefs.generation}"` } });
  });
  await page.goto('/#/settings');
  await expect(page.getByRole('button', { name: '保存偏好', exact: true })).toBeVisible();
  return { writes };
}

test('reading preferences do not silently discard changes made while a save is pending', async ({ page }) => {
  const { writes } = await setup(page);
  let release!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; });
  let pending = false;
  await page.route('**/api/v1/settings/preferences', async route => {
    if (route.request().method() !== 'PATCH') return route.fallback();
    pending = true;
    await wait;
    return route.fallback();
  });
  const locale = page.getByLabel('默认翻译语言', { exact: true });
  await locale.selectOption('ja');
  await page.getByRole('button', { name: '保存偏好', exact: true }).click();
  await expect.poll(() => pending).toBe(true);
  await expect(locale).toBeDisabled();
  await expect(page.getByLabel('管理界面主题', { exact: true })).toBeDisabled();
  await expect(page.locator('#settings-reading').getByRole('button', { name: '查找语言' })).toBeDisabled();
  await page.screenshot({ path: outputDirectory('reading-save-pending.png'), fullPage: true });
  release();
  await expect(page.getByText('偏好已保存。', { exact: true })).toBeVisible();
  await page.screenshot({ path: outputDirectory('reading-save-completed.png'), fullPage: true });
  expect(writes).toEqual([{ path: '/settings/preferences', body: { locale: 'ja', theme: 'light' } }]);
  await expect(locale).toHaveValue('ja');
  await expect(locale).toBeEnabled();
  await locale.selectOption('fr');
  await expect(page.locator('.settings-draft-summary')).toContainText('阅读偏好');
  await expect(page.getByText('偏好已保存。', { exact: true })).toHaveCount(0);
});

test('language search keeps keyboard focus within reachable controls and preserves value when closing', async ({ page }) => {
  await setup(page);
  const group = page.locator('#settings-reading .language-picker');
  const trigger = group.getByRole('button', { name: '查找语言' });
  await trigger.focus();
  await page.keyboard.press('Enter');
  const search = group.getByRole('combobox', { name: '搜索语言名称或代码' });
  await expect(search).toBeFocused();
  await search.fill('zh-H');
  await search.press('ArrowDown');
  await expect(group.getByRole('listbox').getByRole('option', { selected: true })).toContainText('zh-Hant');
  await search.press('Enter');
  await expect(trigger).toBeFocused();
  await expect(page.getByLabel('默认翻译语言', { exact: true })).toHaveValue('zh-Hant');
  await trigger.press('Enter');
  await expect(search).toBeFocused();
  await search.press('Tab');
  await expect(group.getByRole('button', { name: '关闭', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(trigger).toBeFocused();
  await expect(page.getByLabel('默认翻译语言', { exact: true })).toHaveValue('zh-Hant');
});

for (const form of [
  { name: 'reading', field: '管理界面主题', first: 'dark', second: 'system', button: '保存偏好', notice: '偏好已保存。', select: true },
  { name: 'parser', field: '解析超时（分钟）', first: '90', second: '80', button: '保存解析设置', notice: '解析设置已保存。' },
  { name: 'resources', field: '主任务并发上限', first: '3', second: '4', button: '保存资源设置', notice: '资源设置已保存，将用于后续任务调度。' },
]) test(`${form.name} new changes do not keep a stale saved confirmation`, async ({ page }) => {
  await setup(page);
  if (form.name === 'resources') await page.locator('.settings-resource-details > summary').click();
  const field = page.getByLabel(form.field, { exact: true });
  if (form.select) await field.selectOption(form.first); else await field.fill(form.first);
  await page.getByRole('button', { name: form.button, exact: true }).click();
  await expect(page.getByText(form.notice, { exact: true })).toBeVisible();
  if (form.select) await field.selectOption(form.second); else await field.fill(form.second);
  await expect(page.locator('.settings-draft-summary')).toBeVisible();
  await expect(page.getByText(form.notice, { exact: true })).toHaveCount(0);
});
