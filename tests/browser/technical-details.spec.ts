import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';

async function fixture(page: Page, profileOverrides: Record<string, unknown> = {}) {
  const writes: string[] = [];
  const profile = { generation: 3, provider: 'anthropic', configured: true, dispatch_configuration_ready: true,
    api_protocol: 'claude_messages', auth_mode: 'api_key', api_version: '2023-06-01',
    endpoint: 'https://example.invalid/v1/messages', model_id: 'test-translator', profile_revision: 'public-profile-revision',
    profile_hash: 'public-profile-hash', price_revision: 'price-revision', privacy_revision: 'privacy-revision', cost_control_enabled: false, ...profileOverrides };
  const doc = { id: 'doc', title: '技术层级样本', generation: 3, source_revision_id: 'source-revision', lifecycle: 'active', tags: [],
    editions: [{ id: 'edition', target_locale: 'zh-Hans' }] };
  const preflight = { import_id: 'parsed', document_id: 'doc', source_revision_id: 'source-revision', source_hash: 'a'.repeat(64),
    generation: 3, preflight_generation: 3, source_language: 'en', status: 'ready', page_count: 1, block_count: 1,
    required_blocks: 1, retained_blocks: 0, unresolved_blocks: 0, profile, profile_hash: profile.profile_hash, issues: [],
    blocks: [{ id: 'b1', kind: 'paragraph', normalized_text: 'Original text.' }] };
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice('/api/v1'.length);
    if (request.method() !== 'GET') writes.push(path);
    const response = ({
      '/capabilities': {}, '/settings/provider': profile, '/settings/preferences': { generation: 3, locale: 'zh-Hans', theme: 'light' },
      '/imports/parsed/preflight': preflight, '/documents/doc': doc,
      '/editions/edition/preflight': { ...preflight, profile, can_translate: true, locale: 'zh-Hans' },
      '/drafts/draft/translation-preflight': { ...preflight, profile, can_translate: true, locale: 'zh-Hans' },
      '/drafts/draft': { id: 'draft', document_id: 'doc', edition_id: 'edition', source_revision_id: preflight.source_revision_id,
        source_hash: preflight.source_hash, generation: 3, target_locale: 'zh-Hans', glossary_revision: 'glossary-revision',
        segments: [{ block_id: 'b1', source_hash: 's1', source_text: 'Original text.', target_inline: [{ type: 'text', text: '原文。' }], version: 1, review_status: 'not_reviewed' }] },
    } as Record<string, unknown>)[path] ?? { items: [], models: [] };
    await route.fulfill({ json: response, headers: { ETag: '"3"' } });
  });
  return writes;
}

for (const flow of ['preflight', 'edition', 'candidate'] as const) {
  test(`${flow} keeps destination and model visible while technical details remain explicit`, async ({ page }) => {
    const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
    const writes = await fixture(page);
    await page.goto({ preflight: '/#/preflight/parsed', edition: '/#/documents/doc', candidate: '/#/drafts/draft' }[flow]);
    if (flow === 'edition') await page.getByRole('button', { name: '确认此语言版翻译', exact: true }).click();
    if (flow === 'candidate') {
      await page.getByLabel('选择段落 b1', { exact: true }).check();
      await page.getByText('批量处理（已选 1 段）', { exact: true }).click();
      await page.getByRole('button', { name: '局部重译（1 段）', exact: true }).click();
    }
    const container = flow === 'preflight' ? page.locator('main') : page.getByRole('dialog');
    const service = container.getByRole('region', { name: '本次翻译服务', exact: true });
    await expect(service.getByText('https://example.invalid/v1/messages', { exact: true })).toBeVisible();
    await expect(service.getByText('test-translator', { exact: true })).toBeVisible();
    await expect(service.getByText('2023-06-01', { exact: true })).toBeHidden();
    await expect(container.getByText('public-profile-revision', { exact: true })).toBeHidden();
    if (flow !== 'candidate') await expect(container.getByText('a'.repeat(64), { exact: true })).toBeHidden();
    const consent = container.getByRole('checkbox', { name: /同意.*(?:必要|所选|上述)/ });
    await consent.check();
    await service.getByText('连接技术详情', { exact: true }).click();
    await expect(service.getByText('2023-06-01', { exact: true })).toBeVisible();
    await container.getByText(flow === 'edition' ? '来源与配置技术详情' : '翻译配置技术详情', { exact: true }).click();
    await expect(container.getByText('public-profile-revision', { exact: true })).toBeVisible();
    if (flow === 'preflight') await container.getByText('来源技术详情', { exact: true }).click();
    if (flow !== 'candidate') await expect(container.getByText('a'.repeat(64), { exact: true })).toBeVisible();
    await expect(consent).toBeChecked();
    expect(writes).toEqual([]); expect(errors).toEqual([]);
    if (flow === 'candidate') {
      await container.getByRole('button', { name: '关闭', exact: true }).click();
      await page.getByText('翻译依据与原文', { exact: true }).click();
      await expect(page.locator('main').getByRole('link', { name: '术语表', exact: true })).toHaveAttribute('href', '#/glossary?document=doc');
    }
  });
}

for (const flow of ['upload', 'preflight', 'edition', 'candidate', 'continuation'] as const) {
  test(`${flow} shows the exact local model name with its full ID in details`, async ({ page }) => {
    const modelId = 'sha256:' + 'a'.repeat(64);
    const writes = await fixture(page, { api_protocol: 'local_translation', provider: 'local', auth_mode: 'none',
      endpoint: 'http://local-translator:8090/v1/completions', model_id: modelId, model_display_name: 'Pinned Translator Q4' });
    await page.goto({ upload: '/#/upload', preflight: '/#/preflight/parsed', edition: '/#/documents/doc',
      candidate: '/#/drafts/draft', continuation: '/#/drafts/draft' }[flow]);
    if (flow === 'edition') await page.getByRole('button', { name: '确认此语言版翻译', exact: true }).click();
    if (flow === 'continuation') await page.getByRole('button', { name: '翻译未完成内容', exact: true }).click();
    if (flow === 'candidate') {
      await page.getByLabel('选择段落 b1', { exact: true }).check();
      await page.getByText('批量处理（已选 1 段）', { exact: true }).click();
      await page.getByRole('button', { name: '局部重译（1 段）', exact: true }).click();
    }
    const service = page.getByRole('region', { name: '本次翻译服务', exact: true });
    await expect(service.getByText('Pinned Translator Q4', { exact: true })).toBeVisible();
    await expect(service.getByText('http://local-translator:8090/v1/completions', { exact: true })).toBeVisible();
    await expect(service.getByText(modelId, { exact: true })).toBeHidden();
    await service.getByText('连接技术详情', { exact: true }).click();
    await expect(service.getByText(modelId, { exact: true })).toBeVisible();
    expect(writes).toEqual([]);
  });
}

test('unknown local model remains visible by its exact ID', async ({ page }) => {
  await fixture(page, { api_protocol: 'local_translation', provider: 'local', auth_mode: 'none', model_id: 'sha256:unknown' });
  await page.goto('/#/upload');
  await expect(page.getByRole('region', { name: '本次翻译服务', exact: true }).getByText('sha256:unknown', { exact: true })).toBeVisible();
});
