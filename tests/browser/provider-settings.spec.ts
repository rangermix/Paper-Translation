import { test, expect, type Page, type Route } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';

const profile = {
  generation: 7, configured: true, config_source: 'managed', has_api_key: true,
  credential_status: 'configured', provider: 'openai', endpoint: 'https://service.example/v1/responses',
  api_protocol: 'responses', auth_mode: 'bearer', model_id: 'example-model',
  profile_revision: 'server-profile-7', profile_hash: 'a'.repeat(64), config_revision: 'c'.repeat(32),
  credential_revision: 'd'.repeat(32), prompt_version: 'translate-v1', privacy_revision: 'privacy-v1',
  enabled_pairs: [['en', 'zh-Hans']], max_input_tokens: 16000, max_output_tokens: 4000,
  max_unit_characters: 2000, semantic_review_enabled: false,
  price: { revision: 'server-price-7', currency: 'USD', input_micro_per_million: 1250000,
    cached_input_micro_per_million: 250000, output_micro_per_million: 5000000,
    output_includes_reasoning: true, input_bound_rule: 'utf8-byte-ceiling-v1' },
};
type Write = { body: Record<string, any>; headers: Record<string, string>; url: string };
async function setup(page: Page, value: Record<string, unknown> = profile, put?: (route: Route) => Promise<void>) {
  const writes: Write[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/v1/settings/provider') {
      if (request.method() === 'PUT') {
        writes.push({ body: request.postDataJSON(), headers: request.headers(), url: request.url() });
        if (put) return put(route);
        return route.fulfill({ json: { ...profile, ...request.postDataJSON().profile, generation: 8,
          has_api_key: !request.postDataJSON().clear_api_key, dispatch_configuration_ready: !request.postDataJSON().clear_api_key, profile_hash: 'b'.repeat(64) }, headers: { ETag: '"8"' } });
      }
      return route.fulfill({ json: value, headers: { ETag: `"${value.generation ?? 0}"` } });
    }
    const payload = path.endsWith('/capabilities') ? { phase: 'M2', source_mime_types: ['application/pdf'] }
      : path.endsWith('/settings/dispatch') ? { generation: 1, dispatch_disabled: true, maintenance: false, unknown_attempts: 0, unknown_micro: 0, inflight_requests: 0 }
      : path.endsWith('/settings/preferences') ? { generation: 1, locale: 'zh-Hans', publish_policy: 'manual_approval', theme: 'light' }
      : { items: [] };
    return route.fulfill({ json: payload });
  });
  await page.goto('/#/settings');
  return { writes, errors };
}
const save = (page: Page) => page.getByRole('button', { name: '保存 AI 服务配置', exact: true });
const keyInput = (page: Page) => page.getByLabel('API 密钥', { exact: true });
const modelInput = (page: Page) => page.getByLabel('模型 ID', { exact: true });
async function fillAdvanced(page: Page) {
  await page.getByText('高级选项：价格与请求限制', { exact: true }).click();
  await page.getByLabel('输入价格（USD / 百万 token）', { exact: true }).fill('1.25');
  await page.getByLabel('缓存输入价格（USD / 百万 token）', { exact: true }).fill('0.25');
  await page.getByLabel('输出价格（USD / 百万 token）', { exact: true }).fill('5');
  await page.getByLabel('单次输入 token 上限', { exact: true }).fill('16000');
  await page.getByLabel('单次输出 token 上限', { exact: true }).fill('4000');
  await page.getByLabel(/我已核对输出费率适用于推理 token/).check();
}

test('managed service saves only explicit public fields with CAS and preserves an omitted key', async ({ page }) => {
  const { writes, errors } = await setup(page);
  await expect(page.getByRole('heading', { name: 'AI 服务' })).toBeVisible();
  await expect(keyInput(page)).toHaveAttribute('type', 'password');
  await expect(keyInput(page)).toHaveValue('');
  await expect(page.getByText('高级选项：价格与请求限制', { exact: true })).toBeVisible();
  await expect(page.getByLabel('输入价格（USD / 百万 token）', { exact: true })).toBeHidden();
  await modelInput(page).fill('local-model:latest');
  await save(page).click();
  await expect(page.getByRole('status').filter({ hasText: '配置已保存' })).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0].headers['if-match']).toBe('"7"');
  expect(writes[0].headers['x-library-request']).toBe('1');
  expect(writes[0].headers['idempotency-key']).toBeTruthy();
  expect(writes[0].body.api_key).toBeUndefined();
  expect(writes[0].body.profile.model_id).toBe('local-model:latest');
  for (const field of ['profile_hash', 'config_revision', 'credential_revision', 'generation', 'has_api_key', 'costs', 'locale_matrix', 'profile_revision', 'prompt_version', 'privacy_revision']) {
    expect(writes[0].body.profile).not.toHaveProperty(field);
  }
  expect(writes[0].body.profile.price.input_micro_per_million).toBe(1250000);
  expect(writes[0].body.profile.enabled_pairs).toEqual([['en', 'zh-Hans']]);
  expect(errors).toEqual([]);
});

test('complete new service submits actual prices and a password once and stores no browser secret', async ({ page }) => {
  const { writes } = await setup(page, { generation: 0, configured: false, config_source: 'unconfigured', has_api_key: false, enabled_pairs: [] });
  await page.getByLabel('完整请求 URL', { exact: true }).fill('https://service.example/v1/responses');
  await modelInput(page).fill('new-model');
  await keyInput(page).fill('synthetic-test-key-ONLY');
  await fillAdvanced(page);
  await save(page).click();
  await expect(page.getByRole('status').filter({ hasText: '配置已保存' })).toBeVisible();
  expect(writes[0].body.api_key).toBe('synthetic-test-key-ONLY');
  expect(writes[0].body.profile.endpoint).toBe('https://service.example/v1/responses');
  expect(writes[0].body.profile.price).not.toHaveProperty('revision');
  await expect(keyInput(page)).toHaveValue('');
  expect(await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage }, url: location.href }))).not.toContain('synthetic-test-key-ONLY');
  expect(writes.map(x => x.url)).toEqual([new URL('/api/v1/settings/provider', page.url()).href]);
});

test('incomplete configuration can be saved with effective default limits and without inventing prices', async ({ page }) => {
  const { writes } = await setup(page, { generation: 0, configured: false, config_source: 'unconfigured', has_api_key: false, enabled_pairs: [] }, route => route.fulfill({ json: { generation: 1, configured: false, config_source: 'managed', has_api_key: false, api_protocol: 'responses', auth_mode: 'bearer', model_id: 'local-model', missing_fields: ['endpoint', 'price', 'max_input_tokens', 'max_output_tokens'] }, headers: { ETag: '"1"' } }));
  await modelInput(page).fill('local-model');
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile.price).toBeUndefined();
  expect(writes[0].body.profile.max_input_tokens).toBe(32768);
  expect(writes[0].body.profile.max_output_tokens).toBe(8192);
  await expect(page.getByRole('status').filter({ hasText: '配置已保存' })).toContainText('仍等待配置');
});

test('clearing a key is explicit and does not silently select unauthenticated mode', async ({ page }) => {
  const { writes } = await setup(page);
  await page.getByLabel('清除已保存的密钥', { exact: true }).check();
  await expect(keyInput(page)).toBeDisabled();
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.clear_api_key).toBe(true);
  expect(writes[0].body.api_key).toBeUndefined();
  expect(writes[0].body.profile.auth_mode).toBe('bearer');
  await expect(page.locator('.provider-state .pill')).toHaveText('等待配置');
});

test('changing the destination cannot silently rebind an existing key', async ({ page }) => {
  const { writes } = await setup(page);
  await page.getByLabel('完整请求 URL', { exact: true }).fill('https://another.example/v1/chat/completions');
  await page.getByLabel('接口类型', { exact: true }).selectOption('chat_completions');
  await expect(save(page)).toBeDisabled();
  await expect(page.getByText(/服务地址或接口类型已变化/)).toBeVisible();
  await keyInput(page).fill('synthetic-rebind-key');
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile.api_protocol).toBe('chat_completions');
  expect(writes[0].body.api_key).toBe('synthetic-rebind-key');
});

test('explicit local unauthenticated service uses the full URL without adding a route', async ({ page }) => {
  const { writes } = await setup(page, { ...profile, has_api_key: false });
  await page.getByLabel('鉴权方式', { exact: true }).selectOption('none');
  await page.getByLabel('接口类型', { exact: true }).selectOption('chat_completions');
  await page.getByLabel('完整请求 URL', { exact: true }).fill('http://local-ai:11434/v1/chat/completions');
  await expect(keyInput(page)).toBeDisabled();
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile.auth_mode).toBe('none');
  expect(writes[0].body.profile.endpoint).toBe('http://local-ai:11434/v1/chat/completions');
  expect(writes[0].body.api_key).toBeUndefined();
});

test('CAS conflict preserves public edits and requires comparison before using the new generation', async ({ page }) => {
  let fail = true;
  const { writes } = await setup(page, profile, async route => {
    if (fail) return route.fulfill({ status: 412, json: { error: { code: 'GENERATION_MISMATCH', message: 'changed' } } });
    return route.fulfill({ json: { ...profile, generation: 9 }, headers: { ETag: '"9"' } });
  });
  await modelInput(page).fill('my-unsaved-model');
  await keyInput(page).fill('synthetic-ephemeral-key');
  await save(page).click();
  await expect(page.getByRole('alert')).toContainText('版本');
  await expect(modelInput(page)).toHaveValue('my-unsaved-model');
  await expect(keyInput(page)).toHaveValue('');
  await expect(save(page)).toBeDisabled();
  await page.route('**/api/v1/settings/provider', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    return route.fulfill({ json: { ...profile, generation: 8, model_id: 'another-tab-model' }, headers: { ETag: '"8"' } });
  });
  await page.getByRole('button', { name: '读取最新配置', exact: true }).click();
  await expect(page.getByRole('region', { name: '配置版本比较' })).toContainText('another-tab-model');
  await page.getByRole('button', { name: '保留输入并采用最新版本', exact: true }).click();
  await expect(modelInput(page)).toHaveValue('my-unsaved-model');
  fail = false;
  await save(page).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1].headers['if-match']).toBe('"8"');
  expect(writes[1].body.profile.model_id).toBe('my-unsaved-model');
  expect(writes[1].body.api_key).toBeUndefined();
});

test('external key state stays explicitly unverified and requires re-entry before moving endpoints', async ({ page }) => {
  await setup(page, { ...profile, config_source: 'external', has_api_key: null, credential_status: 'external_unverified' });
  await expect(page.getByText('外部密钥状态未核验', { exact: true })).toBeVisible();
  await page.getByLabel('完整请求 URL', { exact: true }).fill('https://different.example/v1/responses');
  await expect(save(page)).toBeDisabled();
});

test('changing only authentication cannot retain a credential under a new binding', async ({ page }) => {
  const { writes } = await setup(page);
  await page.getByLabel('鉴权方式', { exact: true }).selectOption('none');
  await expect(save(page)).toBeDisabled();
  await page.getByLabel('清除已保存的密钥', { exact: true }).check();
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.clear_api_key).toBe(true);
  expect(writes[0].body.profile.auth_mode).toBe('none');
});

test('missing/null prices remain blank while explicitly free rates are preserved exactly', async ({ page }) => {
  const { writes } = await setup(page, { ...profile, price: { ...profile.price, input_micro_per_million: null, cached_input_micro_per_million: null, output_micro_per_million: null } });
  await page.getByText('高级选项：价格与请求限制', { exact: true }).click();
  for (const label of ['输入价格（USD / 百万 token）', '缓存输入价格（USD / 百万 token）', '输出价格（USD / 百万 token）']) {
    await expect(page.getByLabel(label, { exact: true })).toHaveValue('');
    await page.getByLabel(label, { exact: true }).fill('0');
  }
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile.price).toMatchObject({ input_micro_per_million: 0, cached_input_micro_per_million: 0, output_micro_per_million: 0 });
});

test('endpoint rejects credential URL syntax and a pending save cannot be double submitted', async ({ page }) => {
  let finish: (() => void) | undefined;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  const { writes } = await setup(page, profile, async route => { await gate; await route.fulfill({ json: { ...profile, generation: 8 }, headers: { ETag: '"8"' } }); });
  await page.getByLabel('完整请求 URL', { exact: true }).fill('https://user:password@service.example/v1/responses');
  await expect(save(page)).toBeDisabled();
  await page.getByLabel('完整请求 URL', { exact: true }).fill('https://service.example/v1/responses?api_key=synthetic');
  await expect(save(page)).toBeDisabled();
  await page.getByLabel('完整请求 URL', { exact: true }).fill(profile.endpoint);
  await save(page).click();
  await expect(page.getByRole('button', { name: '正在处理配置…' })).toBeDisabled();
  await expect(modelInput(page)).toBeDisabled();
  expect(writes).toHaveLength(1);
  finish!();
  await expect(page.getByRole('status').filter({ hasText: '配置已保存' })).toBeVisible();
});

test('loading failure cannot expose an editable zero-price fallback', async ({ page }) => {
  await setup(page);
  await page.route('**/api/v1/settings/provider', route => route.fulfill({ status: 503, json: { error: { code: 'NOT_READY', message: '配置暂不可读' } } }));
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('配置暂不可读');
  await expect(save(page)).toHaveCount(0);
});

test('provider save errors never echo the submitted key into visible feedback', async ({ page }) => {
  const { writes } = await setup(page, profile, route => route.fulfill({ status: 422, json: { error: { code: 'PROVIDER_CONFIG_INVALID', message: 'rejected synthetic-secret-not-for-display', details: { api_key: 'synthetic-secret-not-for-display' } } } }));
  await keyInput(page).fill('synthetic-secret-not-for-display');
  await save(page).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.locator('body')).not.toContainText('synthetic-secret-not-for-display');
  await expect(keyInput(page)).toHaveValue('');
  expect(writes).toHaveLength(1);
});

test('service settings remain readable and keyboard reachable on desktop and mobile', async ({ page }, testInfo) => {
  const { errors } = await setup(page);
  await expect(page).toHaveTitle('对照文库 · 个人 PDF 知识库');
  await expect(page.getByRole('heading', { name: 'AI 服务' })).toBeVisible();
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  await page.getByLabel('接口类型', { exact: true }).focus();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('鉴权方式', { exact: true })).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath('settings-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath('settings-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.getByText('高级选项：价格与请求限制', { exact: true }).click();
  await expect(page.getByLabel('输入价格（USD / 百万 token）', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('settings-mobile-advanced.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  expect(errors).toEqual([]);
});
