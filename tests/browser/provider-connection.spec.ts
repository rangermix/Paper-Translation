import { test, expect, type Page } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const profile = { generation: 2, profile_hash: 'a'.repeat(64), configured: true, dispatch_configuration_ready: true,
  has_api_key: true, config_source: 'managed', api_protocol: 'responses', auth_mode: 'bearer', model_id: 'test-model',
  endpoint: 'https://service.example/v1/responses', cost_control_enabled: false,
  max_input_tokens: 32768, max_output_tokens: 8192, max_unit_characters: 2000 };
const result = { id: 'job-test', profile_hash: profile.profile_hash, status: 'succeeded', elapsed_ms: 150,
  completed_at: '2026-09-07T05:00:00+00:00', actual_micro: null };
async function setup(page: Page, response = result, value: Record<string, unknown> = profile) {
  const writes: any[] = []; const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (path === '/api/v1/settings/provider/test' && request.method() === 'POST') {
      writes.push({ body: request.postDataJSON(), headers: request.headers() });
      return route.fulfill({ status: 202, json: { ...result, status: 'pending' } });
    }
    if (path === '/api/v1/settings/provider/test/job-test') return route.fulfill({ json: response });
    if (path.endsWith('/settings/dispatch')) return route.fulfill({ json: { generation: 1, dispatch_disabled: true, maintenance: false, unknown_attempts: 0, unknown_micro: 0, inflight_requests: 0 } });
    if (path === '/api/v1/settings/provider') {
      if (request.method() !== 'GET') writes.push({ body: request.postDataJSON(), headers: request.headers() });
      return route.fulfill({ json: value, headers: { ETag: '"2"' } });
    }
    return route.fulfill({ json: path.endsWith('preferences') ? { generation: 1, theme: 'dark' } : { items: [] } });
  });
  await page.goto('/#/settings');
  await expect(page).toHaveURL(/#\/settings$/);
  await expect(page).toHaveTitle(/对照文库/);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  return { writes, errors };
}
const button = (page: Page) => page.getByRole('button', { name: '测试 API 连接 / 密钥', exact: true });

test('connection confirmation sends exactly one test without a key and renders the result', async ({ page }) => {
  const { writes, errors } = await setup(page);
  await button(page).click();
  const dialog = page.getByRole('dialog', { name: '测试 API 连接 / 密钥' });
  await expect(dialog).toContainText('Hello.');
  await expect(dialog).toContainText(profile.endpoint);
  await expect(dialog).toContainText('test-model');
  expect(writes).toHaveLength(0);
  await dialog.getByRole('button', { name: '确认并发送一次测试' }).click();
  await expect(page.getByRole('status').filter({ hasText: '连接测试通过' })).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0].headers['if-match']).toBe('"2"');
  expect(writes[0].body).toEqual({ profile_hash: profile.profile_hash, external_processing_confirmed: true, duplicate_charge_risk_confirmed: false });
  await expect(page.getByText('费用：未计算', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
  await page.locator('.provider-actions').screenshot({ path: outputDirectory('connection-desktop.png') });
});

test('cancel sends nothing and unsaved endpoint or key disables the test', async ({ page }) => {
  const { writes } = await setup(page);
  await button(page).click();
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
  expect(writes).toHaveLength(0);
  await button(page).click();
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click();
  expect(writes).toHaveLength(0);
  await page.getByLabel('API 密钥', { exact: true }).fill('SYNTHETIC_UNSAVED');
  await expect(button(page)).toBeDisabled();
  await expect(page.getByText('请先保存当前修改，再测试连接。', { exact: true })).toBeVisible();
  await page.getByLabel('API 密钥', { exact: true }).fill('');
  await expect(button(page)).toBeEnabled();
  await page.getByLabel('完整请求 URL', { exact: true }).fill('https://changed.example/v1/responses');
  await expect(button(page)).toBeDisabled();
  expect(writes).toHaveLength(0);
});

test('authentication failure is actionable and raw error text is never displayed', async ({ page }) => {
  await setup(page, { ...result, status: 'failed', code: 'PROVIDER_AUTH', message: 'SYNTHETIC_SECRET' } as typeof result);
  await button(page).click();
  await page.getByRole('button', { name: '确认并发送一次测试' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '密钥未通过认证' })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('SYNTHETIC_SECRET');
});

test('unknown result survives reload and a new request needs duplicate charge confirmation', async ({ page }) => {
  const unknown = { ...result, status: 'outcome_unknown', code: 'OUTCOME_UNKNOWN' };
  const { writes } = await setup(page, unknown, { ...profile, connection_test: unknown });
  await expect(page.getByRole('alert').filter({ hasText: '可能已计费' })).toBeVisible();
  expect(writes).toHaveLength(0);
  await button(page).click();
  const send = page.getByRole('button', { name: '确认并发送一次测试' });
  await expect(send).toBeDisabled();
  await page.getByLabel('我接受再次测试可能重复计费的风险').check();
  await send.click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.duplicate_charge_risk_confirmed).toBe(true);
});

test('mobile confirmation fits the viewport and budget is required only when enabled', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { writes } = await setup(page, result, { ...profile, cost_control_enabled: true });
  await button(page).click();
  const send = page.getByRole('button', { name: '确认并发送一次测试' });
  await expect(send).toBeDisabled();
  await page.getByLabel('本次测试预算（USD）').fill('0.10');
  await page.getByLabel('本次测试预算（USD）').press('Enter');
  expect(writes).toHaveLength(0);
  await expect(send).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory('connection-mobile.png'), fullPage: false });
});
