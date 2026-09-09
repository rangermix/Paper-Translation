import { test, expect, type Page } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { outputPath } from './paths';
import { resolve } from 'node:path';

const evidence = process.env.NATIVE_UI_EVIDENCE ? outputPath(process.env.NATIVE_UI_EVIDENCE) : undefined;
const profile = { generation: 3, configured: true, dispatch_configuration_ready: true, config_source: 'managed', has_api_key: true,
  provider: 'openai', api_protocol: 'responses', auth_mode: 'bearer', endpoint: 'https://custom.example/my-service', model_id: 'custom-model:latest',
  profile_hash: 'a'.repeat(64), profile_revision: 'fixture-profile-3', enabled_pairs: [['en', 'zh-Hans']],
  semantic_review_enabled: true, max_input_tokens: 8000, max_output_tokens: 2000,
  price: { currency: 'USD', input_micro_per_million: 1000000, cached_input_micro_per_million: 200000, output_micro_per_million: 2000000,
    output_includes_reasoning: true, input_bound_rule: 'utf8-byte-ceiling-v1', revision: 'fixture-price' } };
const variants = [
  { protocol: 'gemini_interactions', provider: 'gemini', title: 'Gemini Interactions', header: 'x-goog-api-key', endpoint: 'https://generativelanguage.googleapis.com/v1beta/interactions', model: 'gemini-3.8-flash' },
  { protocol: 'claude_messages', provider: 'anthropic', title: 'Claude Messages', header: 'x-api-key', endpoint: 'https://api.anthropic.com/v1/messages', model: 'claude-sonnet-5' },
] as const;
const interfaces = [
  { protocol: 'responses', endpoint: 'https://api.openai.com/v1/responses', model: 'gpt-5.4-mini' },
  { protocol: 'chat_completions', endpoint: 'https://api.openai.com/v1/chat/completions', model: 'gpt-5.4-mini' },
  ...variants,
] as const;
async function setup(page: Page, value: Record<string, unknown> = profile) {
  const writes: { path: string; body: Record<string, any>; headers: Record<string, string> }[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (['error', 'warning'].includes(message.type())) errors.push(message.text()); });
  const doc = { id: 'doc', generation: 1, title: 'Native service contract', lifecycle: 'active', starred: false, tags: [], source_asset_id: 'pdf', source_revision_id: 'source', source_language: 'en', editions: [{ id: 'edition', target_locale: 'zh-Hans' }] };
  const source = { generation: 1, preflight_generation: 1, import_id: 'import', document_id: 'doc', source_revision_id: 'source', source_hash: 'b'.repeat(64), profile_hash: value.profile_hash, source_language: 'en', status: 'ready', unresolved_blocks: 0, page_count: 1, block_count: 1, blocks: [{ id: 'b1', kind: 'paragraph', normalized_text: 'The value is 64.' }] };
  const draft = { id: 'draft', generation: 1, document_id: 'doc', edition_id: 'edition', source_revision_id: 'source', source_hash: source.source_hash, target_locale: 'zh-Hans', glossary_revision: 'empty-v1', source: { language: 'en', protected_atoms: {} }, segments: [{ block_id: 'b1', source_text: 'Original sentence.', source_hash: 'c'.repeat(64), context_hash: 'd'.repeat(64), version: 1, review_status: 'unreviewed', target_inline: [{ type: 'text', text: '已有译文' }] }] };
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const path = new URL(request.url()).pathname.slice(7);
    if (request.method() !== 'GET') {
      writes.push({ path, body: request.postDataJSON(), headers: request.headers() });
      return route.fulfill({ json: path === '/settings/provider' ? { ...value, ...request.postDataJSON().profile, generation: 4, has_api_key: !request.postDataJSON().clear_api_key, dispatch_configuration_ready: !request.postDataJSON().clear_api_key } : { job_id: 'job' }, headers: { ETag: '"4"' } });
    }
    const routes: Record<string, unknown> = { '/settings/provider': value,
      '/settings/dispatch': { generation: 1, dispatch_disabled: true, maintenance: false, unknown_attempts: 0, unknown_micro: 0, inflight_requests: 0 },
      '/settings/preferences': { generation: 1, locale: 'zh-Hans', publish_policy: 'manual_approval' },
      '/capabilities': { phase: 'M2', source_mime_types: ['application/pdf'] }, '/documents/doc': doc, '/drafts/draft': draft,
      '/imports/import/preflight': source, '/glossaries/effective': { revision: 'empty-v1' },
      '/editions/edition/preflight': { ...source, generation: 1, locale: 'zh-Hans', can_translate: true, profile: value },
      '/jobs/job': { id: 'job', generation: 1, status: 'queued', stage: 'translating', control_epoch: 0 }, '/jobs': { items: [] } };
    if (path.endsWith('/events')) return route.abort();
    return route.fulfill({ json: routes[path] ?? { items: [] }, headers: { ETag: path === '/settings/provider' ? '"3"' : '"1"' } });
  });
  return { writes, errors };
}
const save = (page: Page) => page.getByRole('button', { name: '保存 AI 服务配置', exact: true });

// M1-R08/M1-R22: selecting an interface changes the draft, with no implicit save or key reuse.
for (const initial of interfaces) test(`interface defaults replace URL and model when switching from ${initial.protocol}`, async ({ page }) => {
  const { writes, errors } = await setup(page, { ...profile, api_protocol: initial.protocol, has_api_key: false, auth_mode: 'none' });
  await page.goto('/#/settings');
  const selector = page.getByLabel('接口类型', { exact: true });
  const endpoint = page.getByLabel('完整请求 URL', { exact: true });
  const model = page.getByLabel('模型 ID', { exact: true });
  await expect(endpoint).toHaveValue(profile.endpoint);
  await expect(model).toHaveValue(profile.model_id);
  for (const target of [...interfaces.filter(value => value.protocol !== initial.protocol), initial]) {
    await selector.selectOption(target.protocol);
    await expect(endpoint).toHaveValue(target.endpoint);
    await expect(model).toHaveValue(target.model);
    await endpoint.fill('http://local-ai:11434/custom/path');
    await model.fill('my-model:latest');
    await selector.selectOption(target.protocol);
    await expect(endpoint).toHaveValue('http://local-ai:11434/custom/path');
    await expect(model).toHaveValue('my-model:latest');
  }
  expect(writes).toEqual([]);
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile).toMatchObject({ api_protocol: initial.protocol, endpoint: 'http://local-ai:11434/custom/path', model_id: 'my-model:latest' });
  expect(errors).toEqual([]);
});

for (const variant of variants) test(`${variant.protocol} selects its native defaults and key header`, async ({ page }) => {
  const { writes, errors } = await setup(page);
  await page.goto('/#/settings');
  await page.getByLabel('API 密钥', { exact: true }).fill('synthetic-old-intent');
  await page.getByLabel('接口类型', { exact: true }).selectOption(variant.protocol);
  await expect(page.getByLabel('完整请求 URL', { exact: true })).toHaveValue(variant.endpoint);
  await expect(page.getByLabel('模型 ID', { exact: true })).toHaveValue(variant.model);
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('鉴权方式', { exact: true })).toHaveValue('api_key');
  await expect(page.getByLabel('鉴权方式', { exact: true })).toContainText(variant.header);
  await expect(save(page)).toBeDisabled();
  await page.getByLabel('API 密钥', { exact: true }).fill('synthetic-native-key');
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ path: '/settings/provider', body: { profile: { provider: variant.provider, api_protocol: variant.protocol, auth_mode: 'api_key', endpoint: variant.endpoint, model_id: variant.model }, api_key: 'synthetic-native-key' } });
  expect(writes[0].headers['if-match']).toBe('"3"');
  await expect(page.getByLabel('API 密钥', { exact: true })).toHaveValue('');
  expect(await page.evaluate(() => JSON.stringify([location.href, { ...localStorage }, { ...sessionStorage }]))).not.toContain('synthetic-native-key');
  expect(errors).toEqual([]);
});

test('explicit unauthenticated mode survives native protocol switches and sends no key', async ({ page }) => {
  const { writes } = await setup(page, { ...profile, has_api_key: false, auth_mode: 'none' });
  await page.goto('/#/settings');
  for (const variant of variants) {
    await page.getByLabel('接口类型', { exact: true }).selectOption(variant.protocol);
    await expect(page.getByLabel('鉴权方式', { exact: true })).toHaveValue('none');
    await expect(page.getByLabel('API 密钥', { exact: true })).toBeDisabled();
  }
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.api_key).toBeUndefined();
  expect(writes[0].body.profile).toMatchObject({ provider: 'anthropic', auth_mode: 'none' });
});

test('Claude optional version is advanced, validated and omitted when switching to Gemini', async ({ page }) => {
  const { writes } = await setup(page, { ...profile, has_api_key: false });
  await page.goto('/#/settings');
  await page.getByLabel('接口类型', { exact: true }).selectOption('claude_messages');
  await expect(page.getByLabel('Anthropic API 版本', { exact: true })).toBeHidden();
  await page.getByText('高级选项：价格与请求限制', { exact: true }).click();
  await expect(page.getByLabel('Anthropic API 版本', { exact: true })).toHaveAttribute('placeholder', '2023-06-01');
  await page.getByLabel('Anthropic API 版本', { exact: true }).fill('not-a-version');
  await expect(save(page)).toBeDisabled();
  await page.getByLabel('Anthropic API 版本', { exact: true }).fill('2023-06-01');
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile.api_version).toBe('2023-06-01');
  await page.getByLabel('接口类型', { exact: true }).selectOption('gemini_interactions');
  await expect(page.getByLabel('Anthropic API 版本', { exact: true })).toHaveCount(0);
  await page.getByLabel('清除已保存的密钥', { exact: true }).check();
  await save(page).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1].body.profile).not.toHaveProperty('api_version');
});

for (const variant of variants) for (const flow of ['preflight', 'edition', 'candidate', 'semantic'] as const) test(`${variant.protocol} ${flow} consent shows the bound native destination and correct privacy scope`, async ({ page }) => {
  const native = { ...profile, provider: variant.provider, api_protocol: variant.protocol, auth_mode: 'api_key', endpoint: `https://native.example/${variant.protocol}`, ...(variant.protocol === 'claude_messages' ? { api_version: '2023-06-01' } : {}) };
  const { writes } = await setup(page, native);
  await page.goto(flow === 'preflight' ? '/#/preflight/import' : flow === 'edition' ? '/#/documents/doc' : '/#/drafts/draft');
  if (flow === 'edition') await page.getByRole('button', { name: '确认此语言版翻译', exact: true }).click();
  if (flow === 'candidate' || flow === 'semantic') {
    await page.getByRole('button', { name: '展开全部段落', exact: true }).click();
    await page.getByLabel('选择段落 b1', { exact: true }).check();
    await page.getByRole('button', { name: flow === 'candidate' ? /局部重译/ : /辅助语义评审/ }).click();
  }
  const destination = page.getByRole('region', { name: '本次请求目的地' });
  await expect(destination).toContainText(variant.title);
  await expect(destination).toContainText(native.endpoint);
  await expect(destination).toContainText(variant.header);
  if (variant.protocol === 'claude_messages') {
    await expect(destination).toContainText('2023-06-01');
    await expect(page.locator('body')).not.toContainText('store=false');
  }
  if (flow === 'preflight') {
    await page.getByLabel(/本任务费用上限/).fill('0.01');
    
    await page.getByLabel(/同意将必要的源文/).check();
    await page.getByRole('button', { name: '确认外发与预算，开始翻译' }).click();
  } else if (flow === 'edition') {
    await page.getByLabel(/此语言版任务预算/).fill('0.01');
    
    await page.getByLabel(/同意向上述服务地址/).check();
    await page.getByRole('button', { name: '确认外发与预算，翻译此语言版' }).click();
  } else {
    await page.getByLabel(/候选任务预算/).fill('0.01');
    await page.getByLabel(/我同意向上述服务地址/).check();
    await page.getByRole('button', { name: flow === 'candidate' ? '创建局部候选任务' : '创建辅助语义评审任务' }).click();
  }
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile_hash).toBe(native.profile_hash);
});

test('native controls and Claude version remain readable at desktop and mobile sizes', async ({ page }, testInfo) => {
  const { errors } = await setup(page, { ...profile, provider: 'anthropic', api_protocol: 'claude_messages', auth_mode: 'api_key', api_version: '2023-06-01' });
  await page.goto('/#/settings');
  await expect(page).toHaveTitle('对照文库 · 个人 PDF 知识库');
  await expect(page).toHaveURL(/\/#\/settings$/);
  await page.getByLabel('接口类型', { exact: true }).selectOption('gemini_interactions');
  await page.getByLabel('接口类型', { exact: true }).selectOption('claude_messages');
  await expect(page.getByLabel('完整请求 URL', { exact: true })).toHaveValue('https://api.anthropic.com/v1/messages');
  await expect(page.getByLabel('模型 ID', { exact: true })).toHaveValue('claude-sonnet-5');
  await page.getByText('高级选项：价格与请求限制', { exact: true }).click();
  await expect(page.getByLabel('Anthropic API 版本', { exact: true })).toHaveValue('2023-06-01');
  await page.screenshot({ path: evidence ? resolve(evidence, 'native-settings-desktop.png') : testInfo.outputPath('native-settings-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: evidence ? resolve(evidence, 'native-settings-mobile.png') : testInfo.outputPath('native-settings-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('configuration comparison exposes the newest Claude version before retaining edited values', async ({ page }) => {
  const { writes } = await setup(page, { ...profile, has_api_key: false, provider: 'anthropic', api_protocol: 'claude_messages', auth_mode: 'api_key', api_version: '2024-01-01' });
  await page.goto('/#/settings');
  await page.getByText('高级选项：价格与请求限制', { exact: true }).click();
  await page.getByLabel('Anthropic API 版本', { exact: true }).fill('2023-06-01');
  await page.getByRole('button', { name: '读取最新配置', exact: true }).click();
  await expect(page.getByRole('region', { name: '配置版本比较' })).toContainText('2024-01-01');
  await expect(save(page)).toBeDisabled();
  await page.getByRole('button', { name: '保留输入并采用最新版本', exact: true }).click();
  await expect(page.getByLabel('Anthropic API 版本', { exact: true })).toHaveValue('2023-06-01');
  await save(page).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body.profile.api_version).toBe('2023-06-01');
});
