import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const profile = { generation: 1, configured: true, dispatch_configuration_ready: true, config_source: 'managed',
  provider: 'openai', api_protocol: 'responses', auth_mode: 'bearer', has_api_key: true,
  endpoint: 'https://example.invalid/v1/responses', model_id: 'upload-translator', profile_revision: 'profile',
  profile_hash: 'b'.repeat(64), cost_control_enabled: false };
const uploadButton = (page: Page) => page.getByRole('button', { name: /^上传并(翻译|生成原文阅读版)$/ });
const file = (name: string) => ({ name, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7 synthetic') });

async function setup(page: Page, options: { savedHash?: string | null; controlled?: boolean; providerReady?: Promise<void> } = {}) {
  const state = { preferences: { generation: 1, locale: 'ja', publish_policy: 'manual_approval', theme: 'light',
    upload_translation_profile_hash: options.savedHash ?? null },
    provider: { ...profile, cost_control_enabled: options.controlled ?? false }, providerStatus: 200 };
  const writes: { path: string; body: any; headers: Record<string, string> }[] = [], errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' || message.type() === 'warning') errors.push(message.text()); });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (!['GET', 'HEAD'].includes(request.method()) && !path.includes('/chunks/')) {
      writes.push({ path, body: request.postDataJSON(), headers: request.headers() });
    }
    if (path === '/settings/preferences') return route.fulfill({ json: state.preferences, headers: { ETag: '"1"' } });
    if (path === '/settings/provider') {
      await options.providerReady;
      return route.fulfill({ status: state.providerStatus, json: state.providerStatus === 200 ? state.provider
        : { error: { code: 'PROVIDER_UNAVAILABLE', message: '暂时无法读取翻译服务配置。' } }, headers: { ETag: '"1"' } });
    }
    const values: Record<string, unknown> = {
      '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'] },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false, maintenance: false, unknown_attempts: 0, inflight_requests: 0 },
      '/uploads': { upload_id: 'upload', status: 'created', chunk_limit: 4096, generation: 1 },
      '/uploads/upload/chunks/0': { upload_id: 'upload', status: 'uploading', generation: 2 },
      '/uploads/upload/finalize': { upload_id: 'upload', status: 'verified', generation: 3 },
      '/imports': { id: 'doc', generation: 1, title: 'Synthetic upload', status: 'parsing' },
    };
    return route.fulfill({ json: values[path] ?? { items: [] }, headers: { ETag: '"1"' } });
  });
  return { state, writes, errors };
}

async function expectRemovedControls(page: Page) {
  await expect(page.getByRole('checkbox', { name: /同意将所选 PDF/ })).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: '以后上传默认允许翻译', exact: true })).toHaveCount(0);
  await expect(page.getByRole('combobox', { name: '阅读结果', exact: true })).toHaveCount(0);
}

test('submitting a translation batch authorizes the displayed service and automatically publishes every file', async ({ page }) => {
  const { writes, errors } = await setup(page);
  await page.goto('/#/upload');
  await expect(page.getByRole('heading', { name: '上传 PDF', exact: true })).toBeVisible();
  await expectRemovedControls(page);
  const destination = page.getByRole('region', { name: '本次翻译服务', exact: true });
  await expect(destination).toContainText(profile.endpoint);
  await expect(destination).toContainText(profile.model_id);
  await page.locator('#pdf-files').setInputFiles([file('first.pdf'), file('second.pdf')]);
  await uploadButton(page).click();
  await expect.poll(() => writes.filter(row => row.path === '/imports').length).toBe(2);
  for (const row of writes.filter(row => row.path === '/imports')) expect(row.body.workflow).toMatchObject({
    translate: true, external_processing_confirmed: true, use_saved_upload_permission: false, profile_hash: profile.profile_hash,
    preparation: { mode: 'extractive' }, target_locale: 'ja', publish_policy: 'auto_publish',
  });
  expect(writes.some(row => row.path.startsWith('/settings/'))).toBe(false);
  expect(errors).toEqual([]);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
});

test('settings no longer offers saved upload permission or delayed publication', async ({ page }) => {
  const { writes, errors } = await setup(page, { savedHash: profile.profile_hash });
  await page.goto('/#/settings');
  await expect(page.getByLabel('默认翻译语言', { exact: true })).toHaveValue('ja');
  await expect(page.getByRole('checkbox', { name: '以后上传默认允许翻译', exact: true })).toHaveCount(0);
  await expect(page.getByRole('combobox', { name: /发布/ })).toHaveCount(0);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

for (const savedHash of [profile.profile_hash, 'c'.repeat(64)]) test(`legacy ${savedHash === profile.profile_hash ? 'matching' : 'stale'} upload permission does not change explicit batch authorization`, async ({ page }) => {
  const { writes } = await setup(page, { savedHash });
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('legacy.pdf'));
  await uploadButton(page).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body.workflow).toMatchObject({
    translate: true, external_processing_confirmed: true, use_saved_upload_permission: false, profile_hash: profile.profile_hash,
  });
  expect(writes.some(row => row.path === '/settings/preferences')).toBe(false);
});

test('source-only selection never authorizes translation even with legacy permission', async ({ page }) => {
  const { writes } = await setup(page, { savedHash: profile.profile_hash });
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('source.pdf'));
  await page.getByLabel('处理方式', { exact: true }).selectOption('source');
  await uploadButton(page).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body.workflow).toMatchObject({
    translate: false, external_processing_confirmed: false, use_saved_upload_permission: false, publish_policy: 'auto_publish',
  });
});

test('upload uses the current displayed provider hash after the service configuration changes', async ({ page }) => {
  const { state, writes } = await setup(page, { savedHash: profile.profile_hash });
  state.provider.profile_hash = 'c'.repeat(64);
  state.provider.model_id = 'replacement-model';
  state.provider.endpoint = 'https://replacement.invalid/v1/responses';
  await page.goto('/#/upload');
  const destination = page.getByRole('region', { name: '本次翻译服务', exact: true });
  await expect(destination).toContainText(state.provider.endpoint);
  await expect(destination).toContainText(state.provider.model_id);
  await page.locator('#pdf-files').setInputFiles(file('changed.pdf'));
  await uploadButton(page).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body.workflow).toMatchObject({
    external_processing_confirmed: true, profile_hash: state.provider.profile_hash, use_saved_upload_permission: false,
  });
});

test('translation upload waits for provider loading while source-only upload stays available', async ({ page }) => {
  let release!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; });
  const { writes } = await setup(page, { providerReady: waiting });
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('loading.pdf'));
  await expect(uploadButton(page)).toBeDisabled();
  await page.getByLabel('处理方式', { exact: true }).selectOption('source');
  await expect(uploadButton(page)).toBeEnabled();
  await page.getByLabel('处理方式', { exact: true }).selectOption('translate');
  await expect(uploadButton(page)).toBeDisabled();
  expect(writes).toEqual([]);
  release();
  await expect(uploadButton(page)).toBeEnabled();
});

test('provider read errors block translation upload until the current configuration is reloaded', async ({ page }) => {
  const { state, writes } = await setup(page);
  state.providerStatus = 503;
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('provider-error.pdf'));
  const failure = page.getByRole('alert').filter({ hasText: '暂时无法读取翻译服务配置。' }).first();
  await expect(failure.locator('strong')).toHaveText('本次操作未完成，请查看技术详情或稍后重试。');
  await failure.getByText('技术详情', { exact: true }).click();
  await expect(page.getByRole('alert').getByText('暂时无法读取翻译服务配置。', { exact: true }).first()).toBeVisible();
  await expect(uploadButton(page)).toBeDisabled();
  expect(writes).toEqual([]);
  state.providerStatus = 200;
  await page.getByRole('button', { name: '重新读取', exact: true }).click();
  await expect(uploadButton(page)).toBeEnabled();
  await uploadButton(page).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body.workflow.external_processing_confirmed).toBe(true);
});

test('an unconfigured service permits parsing without claiming translation authorization', async ({ page }) => {
  const { state, writes } = await setup(page);
  state.provider.configured = false;
  state.provider.dispatch_configuration_ready = false;
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('unconfigured.pdf'));
  await uploadButton(page).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body.workflow).toMatchObject({
    translate: true, external_processing_confirmed: false, use_saved_upload_permission: false,
  });
});

for (const missing of ['dispatch readiness', 'profile hash']) test(`a service missing ${missing} does not authorize translation`, async ({ page }) => {
  const { state, writes } = await setup(page);
  if (missing === 'dispatch readiness') state.provider.dispatch_configuration_ready = false;
  else state.provider.profile_hash = '';
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('incomplete-provider.pdf'));
  await uploadButton(page).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body.workflow).toMatchObject({
    translate: true, external_processing_confirmed: false, use_saved_upload_permission: false,
  });
  if (missing === 'profile hash') expect(writes.find(row => row.path === '/imports')!.body.workflow).not.toHaveProperty('profile_hash');
});

for (const budget of ['', '0.1']) test(`cost-controlled upload ${budget ? 'submits the explicit budget' : 'can parse while its budget is still missing'}`, async ({ page }) => {
  const { writes } = await setup(page, { controlled: true });
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('budget.pdf'));
  const input = page.getByLabel('每份文档费用上限（USD）', { exact: true });
  await expect(input).toHaveValue('');
  if (budget) await input.fill(budget);
  else await expect(page.getByText('先完成本地解析和原文阅读；翻译将在服务配置和所需预算齐备后开始。', { exact: true })).toBeVisible();
  await uploadButton(page).click();
  await expect.poll(() => writes.some(row => row.path === '/imports')).toBe(true);
  const workflow = writes.find(row => row.path === '/imports')!.body.workflow;
  expect(workflow.external_processing_confirmed).toBe(true);
  if (budget) expect(workflow.budget_micro).toBe(100000);
  else expect(workflow).not.toHaveProperty('budget_micro');
});

test('changing translation preparation is included in the authorized upload request', async ({ page }) => {
  const { writes } = await setup(page);
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('preparation.pdf'));
  await page.getByLabel('翻译前准备', { exact: true }).selectOption('provider');
  await expectRemovedControls(page);
  await uploadButton(page).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body.workflow).toMatchObject({
    preparation: { mode: 'provider' }, external_processing_confirmed: true, use_saved_upload_permission: false,
  });
});

test('mobile upload shows the destination without removed controls or horizontal overflow', async ({ page }) => {
  const { errors } = await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#/upload');
  await expect(page.getByRole('region', { name: '本次翻译服务', exact: true })).toContainText(profile.endpoint);
  await expectRemovedControls(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory('upload-automatic-mobile.png'), fullPage: true });
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('a stale provider refreshes the destination and retries the same uploaded PDF with the new hash', async ({ page }) => {
  const { state, writes } = await setup(page);
  let attempts = 0, refreshing = false, release!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; }), imports: any[] = [];
  await page.route('**/api/v1/settings/provider', async route => {
    if (refreshing) await waiting;
    return route.fallback();
  });
  await page.route('**/api/v1/imports', async route => {
    imports.push(route.request().postDataJSON());
    if (++attempts > 1) return route.fallback();
    refreshing = true;
    state.provider.profile_hash = 'c'.repeat(64);
    state.provider.model_id = 'replacement-model';
    return route.fulfill({ status: 409, json: { error: { code: 'PROFILE_STALE', message: '翻译服务配置已更新，请重新读取后重试。' } } });
  });
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('stale.pdf'));
  await uploadButton(page).click();
  await expect(page.getByText('翻译服务配置已更新，请重新读取后重试。', { exact: true })).toBeVisible();
  const retry = page.getByRole('button', { name: '重新处理已上传的 PDF', exact: true });
  await expect(retry).toBeDisabled();
  release();
  await expect(page.getByRole('region', { name: '本次翻译服务', exact: true })).toContainText('replacement-model');
  await retry.click();
  await expect(page.getByRole('link', { name: /已入库，后台处理中/ })).toBeVisible();
  expect(attempts).toBe(2);
  expect(imports.map(body => body.workflow.profile_hash)).toEqual([profile.profile_hash, state.provider.profile_hash]);
  expect(writes.filter(row => row.path === '/uploads')).toHaveLength(1);
  expect(writes.find(row => row.path === '/imports')?.body.workflow).toMatchObject({
    external_processing_confirmed: true, profile_hash: state.provider.profile_hash, use_saved_upload_permission: false,
  });
});
