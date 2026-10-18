import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';

const pageErrors = new WeakMap<Page, string[]>();
test.beforeEach(({ page }) => { const errors: string[] = []; pageErrors.set(page, errors); page.on('pageerror', error => errors.push(error.message)); });
test.afterEach(({ page }) => { expect(pageErrors.get(page)).toEqual([]); });

async function fixture(page: Page, options: { empty?: boolean; failSecond?: boolean } = {}) {
  const writes: { path: string; etag: string | undefined; body: any }[] = [];
  const segment = (id: string) => ({ block_id: id, version: 1, translatable: true,
    source_text: `Original ${id}`, source_inline: [{ type: 'text', text: `Original ${id}` }],
    target_inline: options.empty && id === 'b1' ? [] : [{ type: 'text', text: `译文 ${id}` }],
    source_hash: `source-${id}`, context_hash: 'context', review_status: 'not_reviewed' });
  const draft: any = { id: 'edit', document_id: 'doc', edition_id: 'edition', generation: 1,
    source_revision_id: 'source', source_hash: 'source-hash', target_locale: 'zh-Hans',
    segments: [segment('b1'), segment('b2'), { ...segment('credit'), translatable: false, target_inline: [] }] };
  let secondFailed = false;
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice('/api/v1'.length);
    if (request.method() !== 'GET') writes.push({ path, etag: request.headers()['if-match'], body: request.postDataJSON() });
    if (path.startsWith('/drafts/edit/segments/') && request.method() === 'PATCH') {
      const id = path.split('/').at(-1), current = draft.segments.find((item: any) => item.block_id === id);
      if (options.failSecond && id === 'b2' && !secondFailed) {
        secondFailed = true; current.version = 9; current.target_inline = [{ type: 'text', text: '另一标签页的译文' }]; draft.generation += 1;
        return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: { code: 'VERSION_CONFLICT', message: '草稿版本已改变' } }) });
      }
      const body = request.postDataJSON();
      expect(request.headers()['if-match']).toBe(`"${draft.generation}"`);
      expect(body.base_segment_version).toBe(current.version);
      current.target_inline = body.target_inline; current.version += 1; draft.generation += 1;
      return route.fulfill({ status: 200, contentType: 'application/json', headers: { ETag: `"${draft.generation}"` }, body: JSON.stringify(draft) });
    }
    const data = path === '/drafts/edit' ? draft : ({
      '/documents/doc': { id: 'doc', title: '编辑保护样本', tags: [], generation: 1, lifecycle: 'active', source_revision_id: 'source', editions: [{ id: 'edition', target_locale: 'zh-Hans', current_artifact_id: 'published' }] },
      '/documents/doc/history': { artifacts: [], publications: [], sources: [], translations: [] },
      '/settings/provider': { configured: false, cost_control_enabled: false },
      '/settings/preferences': { generation: 1, theme: 'dark' },
      '/capabilities': {},
    } as Record<string, unknown>)[path] ?? { items: [], total: 0 };
    await route.fulfill({ status: 200, contentType: 'application/json', headers: { ETag: `"${draft.generation}"` }, body: JSON.stringify(data) });
  });
  return { draft, writes };
}
async function openEditor(page: Page) {
  await page.goto('/#/drafts/edit');
  await expect(page.getByRole('heading', { name: '译文编辑', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '展开全部段落', exact: true }).click();
}
async function change(page: Page, id: string, reason = `修正 ${id}`) {
  const segment = page.locator(`#segment-${id}`);
  await segment.getByRole('textbox', { name: '译文段落', exact: true }).fill(`本地修改 ${id}`);
  if (reason) await segment.getByLabel('修改理由', { exact: true }).fill(reason);
}
const leaveDialog = (page: Page) => page.getByRole('dialog', { name: '有未保存的修改', exact: true });

test('empty targets remain untranslated until an explicit source copy; local text and reasons survive cancellation', async ({ page }) => {
  const { writes } = await fixture(page, { empty: true });
  await openEditor(page);
  const first = page.locator('#segment-b1');
  await expect(first.getByRole('textbox', { name: '译文段落', exact: true })).toBeEmpty();
  await expect(first).toContainText('尚未翻译');
  await expect(first).not.toContainText('译文 · 简体中文');
  await expect(page.locator('.editor-summary')).toContainText('已有阅读版保持不变');
  await expect(page.locator('.editor-summary')).toContainText('1 / 2 段已有译文');
  expect(await page.evaluate(() => !window.dispatchEvent(new Event('beforeunload', { cancelable: true })))).toBe(false);
  await first.getByRole('button', { name: '以原文开始编辑' }).click();
  await expect(first.getByRole('textbox', { name: '译文段落', exact: true })).toHaveText('Original b1');
  await expect(first).toContainText('译文草稿 · 未保存');
  await first.getByLabel('修改理由').fill('人工开始编辑');
  await page.getByRole('link', { name: '文档详情', exact: true }).click();
  await expect(leaveDialog(page)).toBeVisible();
  await leaveDialog(page).getByRole('button', { name: '继续编辑', exact: true }).click();
  await expect(first.getByRole('textbox', { name: '译文段落', exact: true })).toHaveText('Original b1');
  await expect(first.getByLabel('修改理由')).toHaveValue('人工开始编辑');
  expect(writes).toEqual([]);
});

test('Back, Forward, direct hash and refresh cancellation preserve route, selection, inputs and history', async ({ page }) => {
  await fixture(page);
  await page.goto('/#/library');
  await page.evaluate(() => { location.hash = '/drafts/edit'; });
  await expect(page.getByRole('heading', { name: '译文编辑', exact: true })).toBeVisible();
  await page.getByRole('link', { name: '文档详情', exact: true }).click();
  await expect(page).toHaveURL(/#\/documents\/doc$/);
  await expect(page.getByRole('heading', { name: '编辑保护样本', exact: true })).toBeVisible();
  await page.evaluate(() => history.back());
  await expect(page.getByRole('heading', { name: '译文编辑', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '展开全部段落', exact: true }).click();
  await change(page, 'b1'); await change(page, 'b2');
  await page.getByLabel('选择段落 b1', { exact: true }).check();
  for (const direction of ['back', 'forward'] as const) {
    await page.evaluate(value => history[value](), direction);
    await expect(leaveDialog(page)).toBeVisible();
    await expect(page).toHaveURL(/#\/drafts\/edit$/);
    await leaveDialog(page).getByRole('button', { name: '继续编辑', exact: true }).click();
    await expect(page.locator('#segment-b1').getByRole('textbox', { name: '译文段落' })).toHaveText('本地修改 b1');
  }
  await page.evaluate(() => { location.hash = '/jobs'; });
  await expect(leaveDialog(page)).toBeVisible();
  await leaveDialog(page).getByRole('button', { name: '继续编辑', exact: true }).click();
  await expect(page).toHaveURL(/#\/drafts\/edit$/);
  await page.getByRole('button', { name: '刷新版本', exact: true }).click();
  await expect(leaveDialog(page)).toBeVisible();
  await leaveDialog(page).getByRole('button', { name: '继续编辑', exact: true }).click();
  await expect(page.locator('#segment-b2').getByLabel('修改理由')).toHaveValue('修正 b2');
  await expect(page.getByLabel('选择段落 b1', { exact: true })).toBeChecked();
  expect(await page.evaluate(() => !window.dispatchEvent(new Event('beforeunload', { cancelable: true })))).toBe(true);
  const prompt = page.waitForEvent('dialog');
  const reload = page.evaluate(() => location.reload());
  const nativeDialog = await prompt;
  expect(nativeDialog.type()).toBe('beforeunload');
  await nativeDialog.dismiss();
  await reload.catch(() => undefined);
  await expect(page.locator('#segment-b2').getByRole('textbox', { name: '译文段落' })).toHaveText('本地修改 b2');
  await page.evaluate(() => history.back());
  await expect(leaveDialog(page)).toBeVisible();
  await leaveDialog(page).getByRole('button', { name: '放弃修改', exact: true }).click();
  await expect(page).toHaveURL(/#\/library$/);
  await page.evaluate(() => history.forward());
  await expect(page.getByRole('heading', { name: '译文编辑', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '展开全部段落', exact: true }).click();
  await expect(page.locator('#segment-b1').getByRole('textbox', { name: '译文段落' })).toHaveText('译文 b1');
});

test('save before leaving requires actual reasons and serializes all changed segments with fresh ETags', async ({ page }) => {
  const { writes } = await fixture(page);
  await openEditor(page); await change(page, 'b1'); await change(page, 'b2', '');
  await page.getByRole('link', { name: '文档详情', exact: true }).click();
  await leaveDialog(page).getByRole('button', { name: '保存后离开', exact: true }).click();
  await expect(leaveDialog(page)).toContainText('尚有 1 段未填写译文或修改理由');
  expect(writes).toEqual([]);
  await leaveDialog(page).getByRole('button', { name: '继续编辑', exact: true }).click();
  await page.locator('#segment-b2').getByLabel('修改理由').fill('修正 b2');
  await page.getByRole('link', { name: '文档详情', exact: true }).click();
  await leaveDialog(page).getByRole('button', { name: '保存后离开', exact: true }).click();
  await expect(page).toHaveURL(/#\/documents\/doc$/);
  expect(writes.map(write => write.etag)).toEqual(['"1"', '"2"']);
  expect(writes.map(write => write.body.base_segment_version)).toEqual([1, 1]);
  expect(writes.map(write => write.body.reason)).toEqual(['修正 b1', '修正 b2']);
});

for (const trigger of ['back', 'link'] as const) {
  test(`additional history traversal while a ${trigger} leave prompt is open restores the accepted editor route`, async ({ page }) => {
    await fixture(page);
    await page.goto('/#/library');
    await expect(page.getByRole('heading', { name: '文档库', exact: true })).toBeVisible();
    await page.evaluate(() => { location.hash = '/jobs'; });
    await expect(page.getByRole('heading', { name: '任务中心', exact: true })).toBeVisible();
    await page.evaluate(() => { location.hash = '/drafts/edit'; });
    await expect(page.getByRole('heading', { name: '译文编辑', exact: true })).toBeVisible();
    await change(page, 'b1');
    if (trigger === 'back') await page.evaluate(() => history.back());
    else await page.getByRole('link', { name: '文档详情', exact: true }).click();
    await expect(leaveDialog(page)).toBeVisible();
    await expect(page).toHaveURL(/#\/drafts\/edit$/);
    await page.evaluate(() => history.back());
    await expect(page).toHaveURL(/#\/jobs$/);
    await page.evaluate(() => history.back());
    await expect(page).toHaveURL(/#\/library$/);
    await leaveDialog(page).getByRole('button', { name: '继续编辑', exact: true }).click();
    await expect(page).toHaveURL(/#\/drafts\/edit$/);
    await expect(page.locator('#segment-b1').getByRole('textbox', { name: '译文段落' })).toHaveText('本地修改 b1');
    await expect(page.locator('#segment-b1').getByLabel('修改理由')).toHaveValue('修正 b1');
    await page.evaluate(() => history.back());
    await expect(leaveDialog(page)).toBeVisible();
    await leaveDialog(page).getByRole('button', { name: '放弃修改', exact: true }).click();
    await expect(page).toHaveURL(/#\/jobs$/);
    await expect(page.getByRole('heading', { name: '任务中心', exact: true })).toBeVisible();
    await page.evaluate(() => history.forward());
    await expect(page.getByRole('heading', { name: '译文编辑', exact: true })).toBeVisible();
  });
}

test('folding and filtering retain unsaved text, reason, undo and navigation protection', async ({ page }) => {
  await fixture(page); await openEditor(page); await change(page, 'b1');
  const first = page.locator('#segment-b1');
  await page.getByRole('button', { name: '折叠无重要提示的段落', exact: true }).click();
  await expect(first.getByRole('textbox', { name: '译文段落' })).toBeHidden();
  await page.getByRole('combobox', { name: '显示', exact: true }).selectOption('retained');
  await page.getByRole('link', { name: '文档详情', exact: true }).click();
  await expect(leaveDialog(page)).toBeVisible();
  await leaveDialog(page).getByRole('button', { name: '继续编辑', exact: true }).click();
  await page.getByRole('combobox', { name: '显示', exact: true }).selectOption('all');
  await page.getByRole('button', { name: '展开段落 b1', exact: true }).click();
  await expect(first.getByRole('textbox', { name: '译文段落' })).toHaveText('本地修改 b1');
  await expect(first.getByLabel('修改理由')).toHaveValue('修正 b1');
  await first.getByRole('textbox', { name: '译文段落' }).focus();
  await page.keyboard.press('Control+z');
  await expect(first.getByRole('textbox', { name: '译文段落' })).toHaveText('译文 b1');
});

test('replacing a pending hash destination preserves the original requested route', async ({ page }) => {
  await fixture(page); await openEditor(page); await change(page, 'b1');
  await page.evaluate(() => { location.hash = '/jobs'; });
  await expect(leaveDialog(page)).toBeVisible();
  await expect(page).toHaveURL(/#\/drafts\/edit$/);
  await page.evaluate(() => { location.hash = '/library'; });
  await expect(page).toHaveURL(/#\/library$/);
  await leaveDialog(page).getByRole('button', { name: '放弃修改', exact: true }).click();
  await expect(page).toHaveURL(/#\/jobs$/);
  await expect(page.getByRole('heading', { name: '任务中心', exact: true })).toBeVisible();
  await page.evaluate(() => history.back());
  await expect(page.getByRole('heading', { name: '译文编辑', exact: true })).toBeVisible();
  await expect(page.locator('#segment-b1').getByRole('textbox', { name: '译文段落' })).toHaveText('译文 b1');
});

for (const navigation of ['two-hashes', 'synchronous-hashes', 'back-then-hash', 'same-hash'] as const) {
  for (const discard of [false, true]) {
    test(`${navigation} during confirmation ${discard ? 'leaves for the requested route' : 'restores the edited route'} without URL divergence`, async ({ page }) => {
      await fixture(page);
      await page.goto('/#/library');
      await expect(page.getByRole('heading', { name: '文档库', exact: true })).toBeVisible();
      await page.evaluate(() => { location.hash = '/jobs'; });
      await expect(page.getByRole('heading', { name: '任务中心', exact: true })).toBeVisible();
      await page.evaluate(() => { location.hash = '/drafts/edit'; });
      await expect(page.getByRole('heading', { name: '译文编辑', exact: true })).toBeVisible();
      await change(page, 'b1');
      await page.evaluate(() => history.back());
      await expect(leaveDialog(page)).toBeVisible();
      await expect(page).toHaveURL(/#\/drafts\/edit$/);
      if (navigation === 'synchronous-hashes') {
        await page.evaluate(() => { location.hash = '/library'; location.hash = '/settings'; });
      } else {
        if (navigation === 'back-then-hash') {
          await page.evaluate(() => history.back());
          await expect(page).toHaveURL(/#\/jobs$/);
        } else {
          await page.evaluate(() => { location.hash = '/library'; });
          await expect(page).toHaveURL(/#\/library$/);
        }
        await page.evaluate(hash => { location.hash = hash; }, navigation === 'same-hash' ? '/drafts/edit' : '/settings');
      }
      await expect(page).toHaveURL(navigation === 'same-hash' ? /#\/drafts\/edit$/ : /#\/settings$/);
      await leaveDialog(page).getByRole('button', { name: discard ? '放弃修改' : '继续编辑', exact: true }).click();
      await expect(page).toHaveURL(discard ? /#\/jobs$/ : /#\/drafts\/edit$/);
      await expect(page.getByRole('heading', { name: discard ? '任务中心' : '译文编辑', exact: true })).toBeVisible();
      if (!discard) {
        await expect(page.locator('#segment-b1').getByRole('textbox', { name: '译文段落' })).toHaveText('本地修改 b1');
        await expect(page.locator('#segment-b1').getByLabel('修改理由')).toHaveValue('修正 b1');
        await page.getByRole('link', { name: '文档详情', exact: true }).click();
        await expect(leaveDialog(page)).toBeVisible();
        await leaveDialog(page).getByRole('button', { name: '放弃修改', exact: true }).click();
        await expect(page).toHaveURL(/#\/documents\/doc$/);
        await expect(page.getByRole('heading', { name: '编辑保护样本', exact: true })).toBeVisible();
      }
    });
  }
}

test('partial saving keeps failed input and baseline, and requires explicit comparison before merging a newer version', async ({ page }) => {
  const { writes } = await fixture(page, { failSecond: true });
  await openEditor(page); await change(page, 'b1'); await change(page, 'b2');
  await page.getByRole('link', { name: '文档详情', exact: true }).click();
  await leaveDialog(page).getByRole('button', { name: '保存后离开', exact: true }).click();
  await expect(leaveDialog(page)).toContainText('已保存 1 段；其余 1 段仍未保存');
  await expect(page).toHaveURL(/#\/drafts\/edit$/);
  await leaveDialog(page).getByRole('button', { name: '继续编辑', exact: true }).click();
  const first = page.locator('#segment-b1'), second = page.locator('#segment-b2');
  await expect(first.getByText('有未保存修改', { exact: true })).toHaveCount(0);
  await expect(second.getByRole('textbox', { name: '译文段落' })).toHaveText('本地修改 b2');
  await expect(second.getByLabel('修改理由')).toHaveValue('修正 b2');
  await expect(second).toContainText('另一标签页的译文');
  await expect(second).toContainText('当前保存仍使用段落版本 1');
  expect(writes.map(write => write.etag)).toEqual(['"1"', '"2"']);
  await second.getByRole('button', { name: '已对照新版本，保留我的文字继续编辑' }).click();
  await second.getByRole('button', { name: '保存译文', exact: true }).click();
  await expect(second.getByText('有未保存修改', { exact: true })).toHaveCount(0);
  expect(writes.at(-1)?.body.base_segment_version).toBe(9);
  expect(writes.at(-1)?.etag).toBe('"3"');
});

for (const width of [1440, 390]) {
  test(`body is immediately accessible and retained source has a separate count and filter at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await fixture(page);
    await page.goto('/#/drafts/edit');
    const firstInput = page.locator('#segment-b1').getByRole('textbox', { name: '译文段落', exact: true });
    await expect(firstInput).toBeVisible();
    if (width === 390) await page.getByRole('button', { name: '开始编辑正文', exact: true }).click();
    const bounds = await firstInput.boundingBox();
    expect(bounds!.y).toBeLessThan(width === 1440 ? 1000 : 844);
    await change(page, 'b1');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator('.editor-summary')).toContainText('2 段可翻译 · 1 项保留原文');
    await expect(page.locator('#segment-credit')).toBeHidden();
    await page.getByRole('combobox', { name: '显示', exact: true }).selectOption('retained');
    await expect(page.locator('#segment-credit')).toBeVisible();
    await expect(page.locator('#segment-b1')).toBeHidden();
    await expect(page.locator('.editor-segment-tools')).toContainText('显示 0 段可翻译内容、1 项保留原文');
    await page.getByRole('button', { name: '展开段落 credit', exact: true }).click();
    await expect(page.locator('#segment-credit').getByRole('textbox')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
