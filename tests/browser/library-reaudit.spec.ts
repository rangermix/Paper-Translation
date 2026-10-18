import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const original = { id: 'document', generation: 1, title: '原有标题', tags: ['原有标签'], editions: [], source_revision_id: 'source', source_asset_id: 'pdf', lifecycle: 'active' };
async function mockBase(page: Page) {
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path.endsWith('/settings/preferences') ? { generation: 1, locale: 'zh-Hans', theme: 'light' }
      : path.endsWith('/documents/document') ? original : { items: [] }, headers: { ETag: '"1"' } });
  });
}

for (const decision of ['keep', 'latest']) test(`directory edits retain their original CAS baseline until an explicit ${decision} decision`, async ({ page }) => {
  await page.setViewportSize({ width: decision === 'keep' ? 390 : 1440, height: 844 });
  await mockBase(page);
  let saved = { ...original };
  const writes: { etag?: string; body: { title: string; tags: string[] } }[] = [];
  await page.route('**/api/v1/documents/document', async route => {
    const request = route.request();
    if (request.method() === 'GET') return route.fulfill({ json: saved, headers: { ETag: `"${saved.generation}"` } });
    const write = { etag: request.headers()['if-match'], body: request.postDataJSON() };
    writes.push(write);
    if (write.etag !== `"${saved.generation}"`) return route.fulfill({ status: 409, json: { error: { code: 'VERSION_CONFLICT', message: '目录信息已更新。' } } });
    saved = { ...saved, ...write.body, generation: saved.generation + 1 };
    return route.fulfill({ json: saved, headers: { ETag: `"${saved.generation}"` } });
  });
  await page.goto('/#/documents/document');
  await page.getByRole('button', { name: '编辑标题与标签' }).click();
  const dialog = page.getByRole('dialog', { name: '编辑目录信息' });
  await dialog.getByRole('textbox', { name: '标题', exact: true }).fill('我的未保存标题');
  saved = { ...original, generation: 2, title: '其他页面的新标题', tags: ['远端标签'] };
  await expect(dialog.getByRole('region', { name: '目录信息已更新' })).toContainText(saved.title, { timeout: 8000 });
  await expect(dialog.getByRole('textbox', { name: '标题', exact: true })).toHaveValue('我的未保存标题');
  expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.screenshot({ path: outputDirectory(`metadata-comparison-${decision}.png`) });
  await dialog.getByRole('button', { name: '保存目录信息', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({ etag: '"1"', body: { title: '我的未保存标题', tags: ['原有标签'] } });
  await expect(dialog.getByRole('alert')).toBeVisible();
  await expect(dialog.getByRole('textbox', { name: '标题', exact: true })).toHaveValue('我的未保存标题');
  await dialog.getByRole('button', { name: decision === 'keep' ? '保留我的输入，继续编辑' : '使用最新内容', exact: true }).click();
  await expect(dialog.getByRole('region', { name: '目录信息已更新' })).toHaveCount(0);
  const expected = decision === 'keep' ? { title: '我的未保存标题', tags: ['原有标签'] } : { title: saved.title, tags: saved.tags };
  await expect(dialog.getByRole('textbox', { name: '标题', exact: true })).toHaveValue(expected.title);
  expect(writes).toHaveLength(1);
  await dialog.getByRole('button', { name: '保存目录信息', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(writes[1]).toEqual({ etag: '"2"', body: expected });
});

test('history distinguishes read failure from a confirmed empty history and supports retry', async ({ page }) => {
  await mockBase(page); let unavailable = true;
  await page.route('**/api/v1/documents/document/history', route => unavailable
    ? route.fulfill({ status: 503, json: { error: { code: 'SERVICE_UNAVAILABLE', message: 'History temporarily unavailable' } } })
    : route.fulfill({ json: { artifacts: [], sources: [], translations: [] } }));
  await page.goto('/#/history/document');
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByText('尚无阅读版本', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: outputDirectory('history-read-failed.png') });
  unavailable = false;
  await page.getByRole('button', { name: '重新读取', exact: true }).click();
  await expect(page.getByText('尚无阅读版本', { exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('long search translations retain a short safely highlighted excerpt around the match', async ({ page }) => {
  await mockBase(page);
  await page.route('**/api/v1/search?**', route => route.fulfill({ json: { items: [{ document_id: 'document', title: original.title,
    artifact_id: 'artifact', block_id: 'block', locale: 'zh-Hans', source_text: 'source text', target_text: '长译文。'.repeat(600) + '<needle>' + '后文。'.repeat(100) }] } }));
  await page.goto('/#/search?q=%3Cneedle%3E&scope=body&side=target');
  const target = page.locator('.target-snippet');
  await expect(target.locator('mark')).toHaveText('<needle>');
  expect((await target.textContent())!.length).toBeLessThan(330);
  await expect(target.locator('needle')).toHaveCount(0);
});
