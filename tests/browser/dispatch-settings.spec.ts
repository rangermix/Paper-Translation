import { test, expect, type Page } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const initial = { generation: 3, dispatch_disabled: true, maintenance: false, unknown_attempts: 0, unknown_micro: 0, inflight_requests: 0 };
async function setup(page: Page, extra: Record<string, unknown> = {}, fail?: string) {
  let state = { ...initial, ...extra };
  const writes: any[] = [], errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    if (!['GET', 'HEAD'].includes(req.method())) writes.push({ path, body: req.postDataJSON(), headers: req.headers() });
    if (path.endsWith('/settings/dispatch')) {
      if (req.method() === 'PATCH') {
        if (fail) return route.fulfill({ status: 412, json: { error: { code: 'PRECONDITION_FAILED', message: 'unsafe server text' } } });
        state = { ...state, dispatch_disabled: req.postDataJSON().dispatch_disabled, generation: state.generation + 1 };
      }
      return route.fulfill({ json: state, headers: { ETag: `"${state.generation}"` } });
    }
    if (path.endsWith('/settings/provider')) return route.fulfill({ json: {
      generation: 2, configured: true, dispatch_configuration_ready: true, has_api_key: true, config_source: 'managed',
      endpoint: 'https://service.example/v1/responses', model_id: 'example-model', api_protocol: 'responses',
      auth_mode: 'bearer', cost_control_enabled: false, profile_hash: 'a'.repeat(64), dispatch_disabled: state.dispatch_disabled,
    }, headers: { ETag: '"2"' } });
    return route.fulfill({ json: path.endsWith('preferences') ? { generation: state.generation, theme: 'dark' } : { items: [] } });
  });
  await page.goto('/#/settings');
  await expect(page).toHaveTitle(/对照文库/);
  return { writes, errors };
}
const panel = (page: Page) => page.getByRole('region', { name: '外部 API 请求', exact: true });
const allow = (page: Page) => panel(page).getByRole('checkbox', { name: '允许外部 API 请求', exact: true });
const save = (page: Page) => panel(page).getByRole('button', { name: '保存外部请求设置' });

test('enable and pause persist across reload, without saving a key or calling a model', async ({ page }) => {
  const { writes, errors } = await setup(page);
  await expect(panel(page).getByText('已暂停', { exact: true })).toBeVisible();
  await expect(allow(page)).not.toBeChecked();
  await page.getByLabel('API 密钥', { exact: true }).fill('SYNTHETIC_UNSAVED_KEY');
  await allow(page).check();
  expect(writes).toHaveLength(0);
  await save(page).click();
  await expect(panel(page).getByText('已允许', { exact: true })).toBeVisible();
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('SYNTHETIC_UNSAVED_KEY');
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({ path: '/api/v1/settings/dispatch', body: { dispatch_disabled: false }, headers: { 'if-match': '"3"' } });
  expect(JSON.stringify(writes)).not.toContain('SYNTHETIC_UNSAVED_KEY');
  await page.reload();
  await expect(allow(page)).toBeChecked();
  await allow(page).uncheck();
  await save(page).click();
  await expect(panel(page).getByText('已暂停', { exact: true })).toBeVisible();
  expect(writes).toHaveLength(2);
  expect(writes[1].headers['if-match']).toBe('"4"');
  expect(errors).toEqual([]);
  await panel(page).screenshot({ path: outputDirectory('dispatch-desktop.png') });
});

test('unknown costs require acknowledgment and a note, and remain visible after enabling', async ({ page }) => {
  const { writes } = await setup(page, { unknown_attempts: 2, unknown_micro: null });
  await allow(page).check();
  await expect(panel(page)).toContainText('未计算');
  await expect(save(page)).toBeDisabled();
  await panel(page).getByLabel('我已核对未知请求，并接受保留其潜在费用后继续外发').check();
  await expect(save(page)).toBeDisabled();
  await panel(page).getByLabel('风险确认说明').fill('已在服务商后台核对，保留未知费用。');
  await save(page).click();
  await expect(panel(page).getByText('已允许', { exact: true })).toBeVisible();
  expect(writes[0].body).toMatchObject({ dispatch_disabled: false, accept_unknown_risk: true, reason: '已在服务商后台核对，保留未知费用。' });
  await expect(panel(page)).toContainText('2 个请求');
  await expect(panel(page).getByLabel('风险确认说明')).toHaveCount(0);
});

test('stale version preserves edits, blocks resubmit, and offers a fresh read', async ({ page }) => {
  await setup(page, {}, 'stale');
  await allow(page).check(); await save(page).click();
  await expect(panel(page).getByRole('alert')).toContainText('状态已变化');
  await expect(panel(page)).not.toContainText('unsafe server text');
  await expect(allow(page)).toBeChecked();
  await expect(save(page)).toBeDisabled();
  await panel(page).getByRole('button', { name: '读取外部请求状态' }).click();
  await expect(allow(page)).not.toBeChecked();
});

test('maintenance blocks toggling and explains its separate status', async ({ page }) => {
  const { writes } = await setup(page, { maintenance: true });
  await expect(panel(page)).toContainText('正在维护');
  await expect(allow(page)).toBeDisabled();
  await expect(save(page)).toBeDisabled();
  expect(writes).toHaveLength(0);
});

test('mobile switch and risk controls fit the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page, { unknown_attempts: 1, unknown_micro: 25000 });
  await allow(page).check();
  await panel(page).getByLabel('风险确认说明').fill('已核对');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await panel(page).screenshot({ path: outputDirectory('dispatch-mobile.png') });
});
