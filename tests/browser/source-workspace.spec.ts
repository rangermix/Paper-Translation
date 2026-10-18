import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';

const pageErrors = new WeakMap<Page, string[]>();
test.beforeEach(({ page }) => {
  const errors: string[] = []; pageErrors.set(page, errors);
  page.on('pageerror', error => errors.push(error.message));
});
test.afterEach(({ page }) => { expect(pageErrors.get(page)).toEqual([]); });

async function fixture(page: Page, failed = false) {
  const writes: { path: string; body: any; etag?: string }[] = [];
  const bbox = [10, 10, 90, 30], quote = 'Original evidence.';
  const locator = { page: 1, bbox, page_size: [100, 600], page_image_url: '/proof.png' };
  const issues = Array.from({ length: 80 }, (_, index) => ({ id: `issue-${index}`, severity: 'warning', page: index % 4 + 1,
    category: Math.floor(index / 4) % 2 ? 'coverage' : 'numeric', message: '部分内容与原文 PDF 不一致', block_id: 'b1', evidence: { original_record: index } }));
  const doc = { id: 'doc', title: '校对样本', tags: [], generation: 3, source_revision_id: 's', lifecycle: 'active', editions: [] };
  const preflight = { import_id: 'native', document_id: 'doc', source_hash: 'source', generation: 3, preflight_generation: 3,
    source_revision_id: 's', source_language: 'en', status: 'SOURCE_PARSE_REVIEW', unresolved_blocks: 1, required_blocks: 1,
    retained_blocks: 0, unresolved: [{ page: 1, bbox, text: quote }], page_count: 4, block_count: 1, issues,
    quality: { state: failed ? 'failed' : 'completed' },
    blocks: [{ id: 'b1', kind: 'paragraph', owner_id: null, normalized_text: 'Original evidenee.', locators: [locator] }] };
  const draft = { id: 'edit', document_id: 'doc', edition_id: 'e', source_revision_id: 's', source_hash: 'source', generation: 3, target_locale: 'zh-Hans',
    segments: [{ block_id: 'b1', source_hash: 's1', source_text: 'Original evidenee.', source_inline: [{ type: 'text', text: 'Original evidenee.' }],
      target_inline: [{ type: 'text', text: '现有译文' }], version: 1, review_status: 'not_reviewed', locators: [locator] }] };
  const native = { generation: 3, pages: [{ page: 1, page_size: [100, 600], text_regions: [{ bbox, text: quote }] }],
    blocks: [{ block_id: 'b1', native_text: quote, native_regions: [{ page: 1, bbox, text: quote, page_size: [100, 600] }] }] };
  await page.route('**/proof.png', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="600"><rect width="100" height="600" fill="white"/><text x="10" y="20" font-size="4">Original evidence.</text></svg>' }));
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice('/api/v1'.length);
    if (request.method() !== 'GET') {
      writes.push({ path, body: request.postDataJSON(), etag: request.headers()['if-match'] });
      if (failed) return route.fulfill({ status: 409, json: { error: { code: 'VERSION_CONFLICT', message: '源版本已改变' } } });
    }
    const data = ({
      '/capabilities': {}, '/settings/preferences': { generation: 1, theme: 'light', locale: 'zh-Hans' },
      '/settings/provider': { configured: false, cost_control_enabled: false },
      '/documents/doc': doc, '/drafts/edit': draft,
      '/imports/native/preflight': preflight, '/imports/native/native-regions': native,
      '/imports/native/corrections': { id: 'next' },
      '/sources/s/corrections': { id: 'created-source', generation: 4, source_hash: 'created-hash' },
      '/sources/drafts/created-source/confirm': { id: 'confirmed' },
    } as Record<string, unknown>)[path] ?? { items: [], models: [], profiles: [] };
    await route.fulfill({ status: 200, contentType: 'application/json', headers: { ETag: path === '/sources/s/corrections' ? '"4"' : '"3"' }, body: JSON.stringify(data) });
  });
  return { writes, preflight };
}

for (const width of [1440, 390]) {
  test(`source workspace retains edits across PDF views, cancellation and failed saving at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const { writes } = await fixture(page, true);
    await page.goto('/#/preflight/native');
    await page.getByRole('button', { name: '查看原文与调整解析', exact: true }).click();
    const workspace = page.getByRole('dialog', { name: '修正原文识别', exact: true });
    await expect(workspace).toBeVisible();
    const bounds = await workspace.boundingBox();
    expect(bounds!.width).toBeLessThanOrEqual(width);
    if (width === 1440) expect(bounds!.width).toBeGreaterThan(1100);
    await workspace.getByLabel('原件核对记录与理由').fill('对照原件保留的校对理由');
    if (width === 390) await workspace.getByRole('button', { name: '原文 PDF', exact: true }).click();
    await workspace.getByLabel('页面缩放', { exact: true }).selectOption('200');
    await expect(workspace.getByRole('region', { name: '原文 PDF 对照', exact: true })).toBeVisible();
    if (width === 390) await workspace.getByRole('button', { name: '修改内容', exact: true }).click();
    await expect(workspace.getByLabel('原件核对记录与理由')).toHaveValue('对照原件保留的校对理由');
    await workspace.getByRole('button', { name: '关闭校对工作区', exact: true }).click();
    const prompt = page.getByRole('dialog', { name: '有未保存的校对输入', exact: true });
    await prompt.getByRole('button', { name: '继续校对', exact: true }).click();
    await expect(workspace.getByLabel('原件核对记录与理由')).toHaveValue('对照原件保留的校对理由');
    await workspace.getByLabel(/我已对照高亮的原文 PDF/).check();
    await workspace.getByRole('button', { name: '创建新来源草稿并重检覆盖', exact: true }).click();
    await expect(workspace.getByRole('alert')).toBeVisible();
    await expect(workspace.getByLabel('原件核对记录与理由')).toHaveValue('对照原件保留的校对理由');
    expect(writes).toHaveLength(1);
    expect(writes[0].etag).toBe('"3"');
    expect(writes[0].body.evidence).toEqual({ page: 1, bbox: [10, 10, 90, 30], quote: 'Original evidence.' });
    await page.screenshot({ path: outputDirectory(`source-workspace-${width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const close = workspace.getByRole('button', { name: '关闭校对工作区', exact: true });
    await close.focus(); await page.keyboard.press('Shift+Tab');
    await expect(workspace.getByRole('button', { name: '取消校对', exact: true })).toBeFocused();
    await page.keyboard.press('Tab'); await expect(close).toBeFocused();
  });
}

test('eighty diagnostics stay grouped, counted and individually inspectable, including a failed check', async ({ page }) => {
  await fixture(page, true); await page.goto('/#/preflight/native');
  await expect(page.locator('.issue-groups')).toContainText('共 80 条提示');
  await expect(page.locator('.issue-group')).toHaveCount(8);
  await expect(page.locator('.issue-group > summary')).toHaveText([1, 2, 3, 4].flatMap(pageNumber => [
    `第 ${pageNumber} 页 · 内容覆盖 · 10 条`, `第 ${pageNumber} 页 · 数字差异 · 10 条`,
  ]));
  await expect(page.locator('.issue:visible')).toHaveCount(0);
  await expect(page.getByText('检查未完成，以下记录不能代表完整检查结果。', { exact: true })).toBeVisible();
  await page.locator('.issue-group').filter({ hasText: '第 1 页 · 数字差异 · 10 条' }).locator(':scope > summary').click();
  await expect(page.locator('.issue:visible')).toHaveCount(10);
  const first = page.locator('.issue:visible').first();
  await first.getByText('诊断详情', { exact: true }).click();
  await expect(first).toContainText('"original_record": 0');
  await expect(page.locator('.issue')).toHaveCount(80);
  await first.getByRole('button', { name: '查看第 1 页原文', exact: true }).click();
  await expect(page.locator('#source-preview')).toBeFocused();
});

test('an empty diagnostic list distinguishes every check state from a completed check', async ({ page }) => {
  const { preflight } = await fixture(page);
  preflight.issues = [];
  for (const [state, message] of [
    ['not_checked', '尚未检查内容。'], ['checking', '正在检查内容。'],
    ['stale', '内容已更新，检查结果待刷新。'], ['failed', '检查未完成，已有内容仍可继续使用。'],
    ['completed', '本次检查未发现问题。'],
  ]) {
    preflight.quality.state = state;
    await page.goto('/#/preflight/native'); await page.reload();
    await expect(page.getByText(message, { exact: true })).toBeVisible();
    await expect(page.locator('.issue')).toHaveCount(0);
    if (state !== 'completed') await expect(page.getByText('本次检查未发现问题。', { exact: true })).toHaveCount(0);
  }
});

test('source drafts are created and confirmed separately; closing the source form restores parent edit protection', async ({ page }) => {
  const { writes } = await fixture(page); await page.goto('/#/drafts/edit');
  const translation = page.locator('#segment-b1').getByRole('textbox', { name: '译文段落', exact: true });
  await page.getByText('翻译依据与原文', { exact: true }).click();
  await page.getByRole('button', { name: '修正原文识别', exact: true }).click();
  const workspace = page.getByRole('dialog', { name: '修正原文识别', exact: true });
  await workspace.getByLabel('原件证据与机械修正理由', { exact: true }).fill('尚未提交的校对输入');
  await workspace.getByRole('button', { name: '取消校对', exact: true }).click();
  await page.getByRole('dialog', { name: '有未保存的校对输入', exact: true }).getByRole('button', { name: '放弃输入', exact: true }).click();
  await expect(workspace).toHaveCount(0);
  await expect(page.getByRole('dialog', { name: '有未保存的修改', exact: true })).toHaveCount(0);
  await expect(translation).toHaveText('现有译文');
  await page.getByRole('button', { name: '修正原文识别', exact: true }).click();
  await workspace.getByLabel('核对后的原文', { exact: true }).fill('Original evidence.');
  await workspace.getByLabel('原件证据与机械修正理由', { exact: true }).fill('原页字形是 evidence');
  await workspace.getByRole('button', { name: '创建来源修正', exact: true }).click();
  await expect(workspace.getByRole('button', { name: '保存新来源修订', exact: true })).toBeVisible();
  expect(writes.map(write => write.path)).toEqual(['/sources/s/corrections']);
  await expect(workspace.getByLabel('核对后的原文', { exact: true })).toBeDisabled();
  await workspace.getByRole('button', { name: '保存新来源修订', exact: true }).click();
  await expect(workspace).toHaveCount(0);
  expect(writes.at(-1)).toEqual({ path: '/sources/drafts/created-source/confirm', body: { source_hash: 'created-hash' }, etag: '"4"' });
  await translation.fill('新的未保存译文');
  await page.getByRole('link', { name: '文档详情', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '有未保存的修改', exact: true })).toBeVisible();
});

for (const status of [200, 409]) {
  test(`native source correction freezes the submitted fields until a ${status} response`, async ({ page }) => {
    await fixture(page);
    let submitted: { reason: string } | undefined;
    let release!: () => void;
    const pending = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/api/v1/imports/native/corrections', async route => {
      submitted = route.request().postDataJSON();
      await pending;
      await route.fulfill({ status, json: status === 200 ? { id: 'next' } : { error: { code: 'VERSION_CONFLICT', message: '源版本已改变' } } });
    });
    await page.goto('/#/preflight/native');
    await page.getByRole('button', { name: '查看原文与调整解析', exact: true }).click();
    const workspace = page.getByRole('dialog', { name: '修正原文识别', exact: true });
    const reason = workspace.getByLabel('原件核对记录与理由');
    await reason.fill('本次提交的校对理由');
    await workspace.getByLabel(/我已对照高亮的原文 PDF/).check();
    await workspace.getByRole('button', { name: '创建新来源草稿并重检覆盖', exact: true }).click();
    try {
      await expect.poll(() => submitted?.reason).toBe('本次提交的校对理由');
      await expect(workspace).toHaveAttribute('aria-busy', 'true');
      await expect(reason).toBeDisabled();
      await expect(workspace.getByRole('combobox', { name: '修正方式', exact: true })).toBeDisabled();
      await expect(workspace.getByLabel('查看全部原生区域（含已覆盖）')).toBeDisabled();
      await page.keyboard.press('Escape');
      await expect(workspace).toBeVisible();
    } finally { release(); }
    if (status === 200) {
      await expect(workspace).toHaveCount(0);
      await expect(page).toHaveURL(/#\/preflight\/next$/);
    } else {
      await expect(reason).toBeEnabled();
      await expect(reason).toHaveValue('本次提交的校对理由');
      await reason.fill('失败后继续修改的校对理由');
      await workspace.getByRole('button', { name: '关闭校对工作区', exact: true }).click();
      await page.getByRole('dialog', { name: '有未保存的校对输入', exact: true }).getByRole('button', { name: '继续校对', exact: true }).click();
      await expect(reason).toHaveValue('失败后继续修改的校对理由');
    }
  });
}
