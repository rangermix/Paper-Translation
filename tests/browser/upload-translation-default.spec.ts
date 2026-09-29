import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const profile = { generation: 1, configured: true, dispatch_configuration_ready: true, config_source: 'managed',
  provider: 'openai', api_protocol: 'responses', auth_mode: 'bearer', has_api_key: true,
  endpoint: 'https://example.invalid/v1/responses', model_id: 'upload-translator', profile_revision: 'profile',
  profile_hash: 'b'.repeat(64), cost_control_enabled: false };
const defaultOption = (page: Page) => page.getByRole('checkbox', { name: '以后上传默认允许翻译', exact: true });
const consent = (page: Page) => page.getByRole('checkbox', { name: /同意将所选 PDF/ });
const uploadButton = (page: Page) => page.getByRole('button', { name: '上传并开始处理', exact: true });
const file = (name: string) => ({ name, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7 synthetic') });

async function setup(page: Page, options: { enabled?: boolean; controlled?: boolean; providerReady?: Promise<void>; failSave?: boolean } = {}) {
  const state = { preferences: { generation: 1, locale: 'ja', publish_policy: 'manual_approval', theme: 'light',
    upload_translation_profile_hash: options.enabled ? profile.profile_hash : null as string | null },
    provider: { ...profile, cost_control_enabled: options.controlled ?? false } };
  const writes: { path: string; body: any; headers: Record<string, string> }[] = [], errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' || message.type() === 'warning') errors.push(message.text()); });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (!['GET', 'HEAD'].includes(request.method()) && !path.includes('/chunks/')) {
      writes.push({ path, body: request.postDataJSON(), headers: request.headers() });
    }
    if (path === '/settings/preferences') {
      if (request.method() === 'PATCH') {
        if (options.failSave) return route.fulfill({ status: 412, json: { error: { code: 'PRECONDITION_FAILED', message: '设置已更新，请重新读取。' } } });
        state.preferences = { ...state.preferences, ...request.postDataJSON(), generation: state.preferences.generation + 1 };
      }
      return route.fulfill({ json: state.preferences, headers: { ETag: `"${state.preferences.generation}"` } });
    }
    if (path === '/settings/provider') {
      await options.providerReady;
      return route.fulfill({ json: state.provider, headers: { ETag: '"1"' } });
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

test('settings opt-in persists after reload and authorizes every file in an upload batch', async ({ page }) => {
  const { writes, errors } = await setup(page);
  await page.goto('/#/settings');
  await expect(defaultOption(page)).not.toBeChecked();
  await defaultOption(page).check();
  await expect(defaultOption(page)).toBeEnabled();
  await expect(defaultOption(page)).toBeChecked();
  expect(writes[0]).toMatchObject({ path: '/settings/preferences', body: { upload_translation_profile_hash: profile.profile_hash }, headers: { 'if-match': '"1"' } });
  await page.reload();
  await expect(defaultOption(page)).toBeChecked();
  await page.getByRole('region', { name: '上传翻译', exact: true }).screenshot({ path: outputDirectory('upload-default-settings.png') });
  await page.goto('/#/upload');
  await expect(page).toHaveURL(/#\/upload$/);
  await expect(page).toHaveTitle(/.+/);
  await expect(page.getByRole('heading', { name: '上传 PDF', exact: true })).toBeVisible();
  await page.locator('#pdf-files').setInputFiles([file('first.pdf'), file('second.pdf')]);
  await expect(consent(page)).toBeChecked();
  await uploadButton(page).click();
  await expect.poll(() => writes.filter(row => row.path === '/imports').length).toBe(2);
  for (const row of writes.filter(row => row.path === '/imports')) expect(row.body.workflow).toMatchObject({
    translate: true, external_processing_confirmed: true, use_saved_upload_permission: true, profile_hash: profile.profile_hash,
    preparation: { mode: 'extractive' }, target_locale: 'ja', publish_policy: 'manual_approval',
  });
  expect(writes.some(row => row.path === '/settings/provider')).toBe(false);
  expect(errors).toEqual([]);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
});

test('default stays off until saved and one-time consent still resets for a new file selection', async ({ page }) => {
  const { writes } = await setup(page);
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('first.pdf'));
  await expect(consent(page)).not.toBeChecked();
  await consent(page).check();
  await page.locator('#pdf-files').setInputFiles(file('second.pdf'));
  await expect(consent(page)).not.toBeChecked();
  await uploadButton(page).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body.workflow.external_processing_confirmed).toBe(false);
});

test('upload can save the default, override one batch, then disable it persistently', async ({ page }) => {
  const { writes } = await setup(page);
  await page.goto('/#/upload');
  await defaultOption(page).check();
  await expect(defaultOption(page)).toBeEnabled();
  await expect(defaultOption(page)).toBeChecked();
  await page.locator('#pdf-files').setInputFiles(file('first.pdf'));
  await expect(consent(page)).toBeChecked();
  await consent(page).uncheck();
  await uploadButton(page).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body.workflow.external_processing_confirmed).toBe(false);
  await page.reload();
  await page.locator('#pdf-files').setInputFiles(file('second.pdf'));
  await expect(consent(page)).toBeChecked();
  await defaultOption(page).uncheck();
  await expect(defaultOption(page)).toBeEnabled();
  await expect(defaultOption(page)).not.toBeChecked();
  await expect(consent(page)).not.toBeChecked();
  await page.reload();
  await expect(defaultOption(page)).not.toBeChecked();
  expect(writes.filter(row => row.path === '/settings/preferences').map(row => row.body.upload_translation_profile_hash)).toEqual([profile.profile_hash, null]);
});

test('source-only selection overrides an enabled default', async ({ page }) => {
  const { writes } = await setup(page, { enabled: true });
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('source.pdf'));
  await page.getByLabel('生成内容', { exact: true }).selectOption('source');
  await uploadButton(page).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body.workflow).toMatchObject({ translate: false, external_processing_confirmed: false });
});

test('a changed provider invalidates the saved permission and requires explicit rebinding', async ({ page }) => {
  const { state, writes } = await setup(page, { enabled: true });
  state.provider.profile_hash = 'c'.repeat(64);
  state.provider.model_id = 'replacement-model';
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('changed.pdf'));
  await expect(defaultOption(page)).not.toBeChecked();
  await expect(consent(page)).not.toBeChecked();
  await expect(page.getByText(/原默认授权已失效/)).toBeVisible();
  await defaultOption(page).check();
  await expect(defaultOption(page)).toBeEnabled();
  await expect(consent(page)).toBeChecked();
  expect(writes[0].body.upload_translation_profile_hash).toBe(state.provider.profile_hash);
});

test('changing preparation clears automatic consent even when returning to extractive preparation', async ({ page }) => {
  await setup(page, { enabled: true });
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('preparation.pdf'));
  await expect(consent(page)).toBeChecked();
  await page.getByLabel('翻译前准备', { exact: true }).selectOption('provider');
  await expect(consent(page)).not.toBeChecked();
  await page.locator('#pdf-files').setInputFiles(file('another.pdf'));
  await expect(consent(page)).not.toBeChecked();
  await page.getByLabel('翻译前准备', { exact: true }).selectOption('extractive');
  await expect(consent(page)).not.toBeChecked();
});

test('saved permission waits for the current provider before allowing an upload', async ({ page }) => {
  let release!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; });
  await setup(page, { enabled: true, providerReady: waiting });
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('loading.pdf'));
  await expect(uploadButton(page)).toBeDisabled();
  release();
  await expect(consent(page)).toBeChecked();
  await expect(uploadButton(page)).toBeEnabled();
});

test('budget is still explicit when cost control is enabled', async ({ page }) => {
  const { writes } = await setup(page, { enabled: true, controlled: true });
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('budget.pdf'));
  await expect(consent(page)).toBeChecked();
  await expect(page.getByLabel('每份文档费用上限（USD）', { exact: true })).toHaveValue('');
  await expect(page.getByText(/翻译将在配置、外发授权和所需预算齐备后开始/)).toBeVisible();
  await page.getByLabel('每份文档费用上限（USD）', { exact: true }).fill('0.1');
  await uploadButton(page).click();
  await expect.poll(() => writes.find(row => row.path === '/imports')?.body.workflow).toMatchObject({ external_processing_confirmed: true, budget_micro: 100000 });
});

test('failed save cannot enable default permission', async ({ page }) => {
  await setup(page, { failSave: true });
  await page.goto('/#/upload');
  await defaultOption(page).click();
  await expect(page.getByText('服务端版本已变化。当前输入仍保留，请读取最新版本后重试。', { exact: true })).toBeVisible();
  await expect(defaultOption(page)).not.toBeChecked();
  await expect(consent(page)).not.toBeChecked();
});

test('mobile upload presents the saved option without overflow or application errors', async ({ page }) => {
  const { errors } = await setup(page, { enabled: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#/upload');
  await expect(consent(page)).toBeChecked();
  await defaultOption(page).scrollIntoViewIfNeeded();
  await expect(defaultOption(page)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory('upload-default-mobile.png') });
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('a revoked default refreshes the form and lets the user confirm the already-uploaded PDF', async ({ page }) => {
  const { state, writes } = await setup(page, { enabled: true });
  await page.route('**/api/v1/imports', route => {
    if (!route.request().postDataJSON().workflow.use_saved_upload_permission) return route.fallback();
    return route.fulfill({ status: 409, json: { error: { code: 'UPLOAD_TRANSLATION_DEFAULT_STALE',
      message: '上传默认授权已更改，请重新读取设置或为本次上传确认授权。' } } });
  });
  await page.goto('/#/upload');
  await page.locator('#pdf-files').setInputFiles(file('revoked.pdf'));
  await expect(consent(page)).toBeChecked();
  state.preferences.upload_translation_profile_hash = null;
  state.preferences.generation++;
  await uploadButton(page).click();
  await expect(page.getByText(/上传默认授权已更改/)).toBeVisible();
  await expect(consent(page)).not.toBeChecked();
  await consent(page).check();
  await page.getByRole('button', { name: '重新处理已上传的 PDF', exact: true }).click();
  await expect(page.getByRole('link', { name: /已入库，后台处理中/ })).toBeVisible();
  expect(writes.filter(row => row.path === '/uploads')).toHaveLength(1);
  expect(writes.find(row => row.path === '/imports')?.body.workflow).toMatchObject({
    external_processing_confirmed: true, use_saved_upload_permission: false,
  });
});
