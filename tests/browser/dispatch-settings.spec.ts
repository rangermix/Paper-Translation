import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const initial = { generation: 3, dispatch_disabled: true, maintenance: false, unknown_attempts: 0, unknown_micro: 0, inflight_requests: 0 };
async function setup(page: Page, extra: Record<string, unknown> = {}, fail?: string, local = false) {
  let state = { ...initial, ...extra };
  const writes: any[] = [], errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && !fail) errors.push(message.text()); });
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
      endpoint: 'https://service.example/v1/responses', model_id: 'example-model', api_protocol: local ? 'local_translation' : 'responses',
      auth_mode: local ? 'none' : 'bearer', cost_control_enabled: false, profile_hash: 'a'.repeat(64), dispatch_disabled: state.dispatch_disabled,
    }, headers: { ETag: '"2"' } });
    if (path.endsWith('/settings/local-models')) return route.fulfill({ json: { models: [] } });
    return route.fulfill({ json: path.endsWith('preferences') ? { generation: state.generation, theme: 'dark' } : { items: [] } });
  });
  await page.goto('/#/settings');
  await expect(page).toHaveURL(/#\/settings$/);
  await expect(page).toHaveTitle(/对照文库/);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  return { writes, errors };
}
const panel = (page: Page) => page.getByRole('region', { name: '模型请求状态', exact: true });
const resume = (page: Page) => panel(page).getByRole('button', { name: '恢复模型请求', exact: true });

for (const local of [false, true]) test(`${local ? 'local' : 'API'} model needs only its request confirmation`, async ({ page }) => {
  const { writes, errors } = await setup(page, { dispatch_disabled: false }, undefined, local);
  await expect(page.getByRole('heading', { name: 'AI 服务', exact: true })).toBeVisible();
  const testName = local ? '测试本地翻译模型' : '测试 API 连接 / 密钥';
  await page.getByRole('button', { name: testName, exact: true }).click();
  await expect(page.getByRole('checkbox', { name: /^允许(模型请求|外部 API 请求)$/ })).toHaveCount(0);
  await expect(panel(page)).toHaveCount(0);
  await expect(page.getByRole('dialog', { name: testName })).toBeVisible();
  expect(writes).toHaveLength(0);
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('button', { name: testName, exact: true })).toBeEnabled();
  await expect(panel(page)).toHaveCount(0);
  expect(writes).toHaveLength(0);
  expect(errors).toEqual([]);
  await page.screenshot({ path: outputDirectory(`dispatch-${local ? 'local' : 'api'}-ready.png`), fullPage: false });
});

test('existing pause can be recovered without saving a key or calling a model', async ({ page }) => {
  const { writes, errors } = await setup(page);
  await expect(panel(page).getByText('已暂停', { exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: /^允许(模型请求|外部 API 请求)$/ })).toHaveCount(0);
  await page.getByLabel('API 密钥', { exact: true }).fill('SYNTHETIC_UNSAVED_KEY');
  expect(writes).toHaveLength(0);
  await resume(page).click();
  await expect(panel(page).getByRole('status')).toContainText('已恢复模型请求');
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('SYNTHETIC_UNSAVED_KEY');
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({ path: '/api/v1/settings/dispatch', body: { dispatch_disabled: false }, headers: { 'if-match': '"3"' } });
  expect(JSON.stringify(writes)).not.toContain('SYNTHETIC_UNSAVED_KEY');
  await page.reload();
  await expect(page.getByRole('button', { name: '测试 API 连接 / 密钥', exact: true })).toBeEnabled();
  await expect(panel(page)).toHaveCount(0);
  expect(writes).toHaveLength(1);
  expect(errors).toEqual([]);
});

test('unknown costs require acknowledgment and a note, and remain visible after enabling', async ({ page }) => {
  const { writes } = await setup(page, { unknown_attempts: 2, unknown_micro: null });
  await expect(panel(page)).toContainText('未计算');
  await expect(resume(page)).toBeDisabled();
  await panel(page).getByLabel('我已核对未知请求，并接受保留其潜在费用后继续外发').check();
  await expect(resume(page)).toBeDisabled();
  await panel(page).getByLabel('风险确认说明').fill('已在服务商后台核对，保留未知费用。');
  await resume(page).click();
  await expect(panel(page).getByRole('status')).toContainText('已恢复模型请求');
  expect(writes[0].body).toMatchObject({ dispatch_disabled: false, accept_unknown_risk: true, reason: '已在服务商后台核对，保留未知费用。' });
  await expect(panel(page)).toContainText('2 个请求');
  await expect(panel(page).getByLabel('风险确认说明')).toHaveCount(0);
});

test('stale version preserves acknowledgment, blocks resubmit, and offers a fresh read', async ({ page }) => {
  await setup(page, { unknown_attempts: 1 }, 'stale');
  await panel(page).getByLabel('我已核对未知请求，并接受保留其潜在费用后继续外发').check();
  await panel(page).getByLabel('风险确认说明').fill('已核对');
  await resume(page).click();
  await expect(panel(page).getByRole('alert')).toContainText('状态已变化');
  await expect(panel(page)).not.toContainText('unsafe server text');
  await expect(panel(page).getByLabel('风险确认说明')).toHaveValue('已核对');
  await expect(resume(page)).toBeDisabled();
  await panel(page).getByRole('button', { name: '刷新请求状态' }).click();
  await expect(panel(page).getByLabel('风险确认说明')).toHaveValue('');
  await expect(resume(page)).toBeDisabled();
});

test('maintenance blocks recovery and explains its separate status', async ({ page }) => {
  const { writes } = await setup(page, { maintenance: true });
  await expect(panel(page)).toContainText('正在维护');
  await expect(resume(page)).toBeDisabled();
  expect(writes).toHaveLength(0);
});

test('mobile recovery and risk controls fit the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page, { unknown_attempts: 1, unknown_micro: 25000 });
  await panel(page).getByLabel('风险确认说明').fill('已核对');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await panel(page).screenshot({ path: outputDirectory('dispatch-mobile.png') });
});
