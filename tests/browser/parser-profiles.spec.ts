import { test, expect, type Page } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

async function setup(page: Page, stale = false) {
  let preferences = { generation: 3, locale: 'zh-Hans', publish_policy: 'manual_approval', theme: 'light', parser_profile_revision: 'docling-v1', parser_timeout_seconds: 7200 };
  const writes: any[] = [], errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    if (!['GET', 'HEAD'].includes(req.method())) writes.push({ path, body: req.postDataJSON(), headers: req.headers() });
    if (path.endsWith('/settings/preferences')) {
      if (req.method() === 'PATCH') {
        if (stale) return route.fulfill({ status: 412, json: { error: { code: 'PRECONDITION_FAILED', message: 'Stale version' } } });
        preferences = { ...preferences, ...req.postDataJSON(), generation: preferences.generation + 1 };
      }
      return route.fulfill({ json: preferences, headers: { ETag: `"${preferences.generation}"` } });
    }
    if (path.endsWith('/settings/provider')) return route.fulfill({ json: { configured: false, dispatch_disabled: true, endpoint: '', model_id: '', generation: 2 } });
    if (path.endsWith('/settings/dispatch')) return route.fulfill({ json: { generation: 3, dispatch_disabled: true, unknown_attempts: 0, inflight_requests: 0 } });
    if (path.endsWith('/capabilities')) return route.fulfill({ json: { phase: 'M2', features: { translation: true }, source_mime_types: ['application/pdf'] } });
    if (path.endsWith('/documents/doc_test')) return route.fulfill({ json: { id: 'doc_test', title: 'Parser choice fixture', source_asset_id: 'asset_test', tags: [], editions: [], generation: 7, lifecycle: 'active', status: 'source_only' } });
    if (path.endsWith('/documents/doc_test/parse')) return route.fulfill({ status: 202, json: { job_id: 'parse_test' } });
    if (path.endsWith('/jobs/parse_test')) return route.fulfill({ json: { id: 'parse_test', stage: 'parse', status: 'pending', control_epoch: 1 } });
    return route.fulfill({ json: { items: [] } });
  });
  return { writes, errors };
}

for (const profile of ['granite-docling-v1', 'paddleocr-vl-1.6-v1']) {
  test(`${profile}: save default, reload, then override for one document`, async ({ page }) => {
    const { writes, errors } = await setup(page);
    await page.goto('/#/settings');
    await expect(page).toHaveTitle(/对照文库/);
    const panel = page.getByRole('region', { name: 'PDF 解析', exact: true });
    await expect(panel.getByLabel('默认 PDF 解析方案')).toHaveValue('docling-v1');
    await expect(panel.getByLabel('解析超时（分钟）')).toHaveValue('120');
    await panel.getByLabel('解析超时（分钟）').fill('180');
    await panel.getByLabel('默认 PDF 解析方案').selectOption(profile);
    expect(writes).toHaveLength(0);
    await panel.getByRole('button', { name: '保存解析设置' }).click();
    await expect(panel).toContainText('解析设置已保存');
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({ path: '/api/v1/settings/preferences', body: { parser_profile_revision: profile, parser_timeout_seconds: 10800 }, headers: { 'if-match': '"3"' } });
    await page.reload();
    await expect(panel.getByLabel('默认 PDF 解析方案')).toHaveValue(profile);
    await expect(panel.getByLabel('解析超时（分钟）')).toHaveValue('180');
    await panel.screenshot({ path: outputDirectory(`${profile}-settings.png`) });
    await page.goto('/#/documents/doc_test');
    await expect(page.getByLabel('本次 PDF 解析方案')).toHaveValue(profile);
    await page.getByLabel('本次 PDF 解析方案').selectOption('docling-v1');
    expect(writes).toHaveLength(1);
    await page.getByRole('button', { name: '解析并生成阅读版', exact: true }).click();
    await expect(page).toHaveURL(/#\/jobs\/parse_test/);
    expect(writes[1]).toMatchObject({ path: '/api/v1/documents/doc_test/parse', body: { source_asset_id: 'asset_test', parser_profile_revision: 'docling-v1' }, headers: { 'if-match': '"7"' } });
    expect(errors).toEqual([]);
  });
}

test('stale save preserves choice and offers refresh without overwriting newer settings', async ({ page }) => {
  const { writes } = await setup(page, true);
  await page.goto('/#/settings');
  const panel = page.getByRole('region', { name: 'PDF 解析', exact: true });
  await panel.getByLabel('默认 PDF 解析方案').selectOption('paddleocr-vl-1.6-v1');
  await panel.getByLabel('解析超时（分钟）').fill('180');
  await panel.getByRole('button', { name: '保存解析设置' }).click();
  await expect(panel.getByRole('alert')).toBeVisible();
  await expect(panel.getByLabel('默认 PDF 解析方案')).toHaveValue('paddleocr-vl-1.6-v1');
  await expect(panel.getByLabel('解析超时（分钟）')).toHaveValue('180');
  await expect(panel.getByRole('button', { name: '保存解析设置' })).toBeDisabled();
  expect(writes).toHaveLength(1);
});

test('invalid timeout blocks writes and valid bounds can be saved', async ({ page }) => {
  const { writes } = await setup(page);
  await page.goto('/#/settings');
  const panel = page.getByRole('region', { name: 'PDF 解析', exact: true });
  const input = panel.getByLabel('解析超时（分钟）');
  const save = panel.getByRole('button', { name: '保存解析设置' });
  for (const value of ['', '0', '1441', '1.5']) {
    await input.fill(value);
    await expect(save).toBeDisabled();
    await expect(input).toHaveAttribute('aria-invalid', 'true');
  }
  expect(writes).toHaveLength(0);
  for (const minutes of [1, 1440]) {
    await input.fill(String(minutes));
    await expect(save).toBeEnabled();
    await save.click();
    await expect(panel).toContainText('解析设置已保存');
    await page.reload();
    await expect(input).toHaveValue(String(minutes));
    expect(writes.at(-1).body.parser_timeout_seconds).toBe(minutes * 60);
  }
  expect(writes).toHaveLength(2);
});

test('mobile parsing controls fit the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { errors } = await setup(page);
  await page.goto('/#/settings');
  const panel = page.getByRole('region', { name: 'PDF 解析', exact: true });
  await panel.getByLabel('默认 PDF 解析方案').selectOption('paddleocr-vl-1.6-v1');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await panel.screenshot({ path: outputDirectory('parser-mobile.png') });
  expect(errors).toEqual([]);
});
