import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

test('saved parse result starts real translation after current-destination confirmation', async ({ page }) => {
  const requests: any[] = [], errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  const profile = { configured: true, provider: 'local', api_protocol: 'local_translation', model_id: 'sha256:6c8b1184cdeda6e89259a4cda227c53919aae0dae5fdc3c272284e808194127c',
    endpoint: 'http://local-translator:8090/v1/completions', profile_revision: 'current-profile', cost_control_enabled: false };
  await page.route('**/api/v1/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice(7);
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    let json: unknown = { items: [] };
    if (path === '/capabilities') json = { phase: 'M2' };
    if (path === '/settings/preferences') json = { theme: 'light', locale: 'zh-Hans' };
    if (path === '/settings/provider') json = profile;
    if (path === '/imports/parsed/preflight') json = { import_id: 'parsed', document_id: 'doc', status: 'sealed',
      generation: 2, page_count: 1, block_count: 1, source_language: 'en', source_hash: 'a'.repeat(64),
      blocks: [{ id: 'b1', kind: 'paragraph', normalized_text: 'A complete parsed paragraph.' }],
      translation_targets: [{ draft_id: 'draft', target_locale: 'zh-Hans' }] };
    if (path === '/drafts/draft/translation-preflight') json = { generation: 3, source_revision_id: 'source',
      source_hash: 'a'.repeat(64), source_language: 'en', locale: 'zh-Hans', profile, profile_hash: 'b'.repeat(64), can_translate: true };
    if (path === '/drafts/draft/translate') {
      requests.push({ body: request.postDataJSON(), etag: request.headers()['if-match'] });
      return route.fulfill({ status: 202, json: { job_id: 'translation' } });
    }
    if (path === '/jobs/translation') json = { id: 'translation', stage: 'translate', status: 'pending', generation: 1, control_epoch: 0 };
    return route.fulfill({ json, headers: { ETag: '"3"' } });
  });
  await page.goto('/#/preflight/parsed');
  await expect(page.getByRole('heading', { name: '解析结果', exact: true })).toBeVisible();
  await page.getByRole('button', { name: /开始翻译/ }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText(profile.model_id, { exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: '开始翻译未完成内容' })).toBeDisabled();
  expect(requests).toEqual([]);
  await dialog.getByRole('checkbox').check();
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory('parse-translation-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory('parse-translation-mobile.png') });
  await dialog.getByRole('button', { name: '开始翻译未完成内容' }).click();
  await expect(page).toHaveURL(/#\/jobs\/translation$/);
  expect(requests).toHaveLength(1);
  expect(requests[0].etag).toBe('"3"');
  expect(requests[0].body).toMatchObject({ external_processing_confirmed: true, source_revision_id: 'source',
    profile_revision: 'current-profile', profile_hash: 'b'.repeat(64), publish_policy: 'auto_publish' });
  expect(errors).toEqual([]);
});

test('paused model requests explain the block and refresh without submitting translation', async ({ page }) => {
  let paused = true, submitted = 0;
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.slice(7);
    if (path.endsWith('/events')) return route.fulfill({ contentType: 'text/event-stream', body: '' });
    let json: unknown = { items: [] };
    if (path === '/capabilities') json = { phase: 'M2' };
    if (path === '/settings/preferences') json = { theme: 'light', locale: 'zh-Hans' };
    if (path === '/imports/parsed/preflight') json = { import_id: 'parsed', document_id: 'doc', status: 'sealed',
      generation: 2, page_count: 1, block_count: 1, source_language: 'en', source_hash: 'a'.repeat(64), blocks: [],
      translation_targets: [{ draft_id: 'draft', target_locale: 'zh-Hans' }] };
    if (path === '/drafts/draft/translation-preflight') json = { generation: 3, source_revision_id: 'source',
      source_hash: 'a'.repeat(64), source_language: 'en', locale: 'zh-Hans', profile_hash: 'b'.repeat(64),
      profile: { configured: true, provider: 'local', api_protocol: 'local_translation', model_id: 'local-model',
        endpoint: 'http://local-translator:8090/v1/completions', profile_revision: 'current', cost_control_enabled: false },
      can_translate: !paused, blocked_reason: paused ? 'DISPATCH_DISABLED' : null };
    if (path.endsWith('/translate')) submitted++;
    return route.fulfill({ json, headers: { ETag: '"3"' } });
  });
  await page.goto('/#/preflight/parsed');
  await page.getByRole('button', { name: /开始翻译/ }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('模型请求已暂停，请在设置中开启请求后刷新状态。')).toBeVisible();
  await dialog.getByRole('checkbox').check();
  await expect(dialog.getByRole('button', { name: '开始翻译未完成内容' })).toBeDisabled();
  paused = false;
  await dialog.getByRole('button', { name: '刷新状态' }).click();
  await expect(dialog.getByText('模型请求已暂停，请在设置中开启请求后刷新状态。')).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: '开始翻译未完成内容' })).toBeEnabled();
  expect(submitted).toBe(0);
});
