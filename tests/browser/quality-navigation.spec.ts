import { test, expect } from '../../apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';
import { resolve } from 'node:path';

for (const width of [1440, 390]) {
  test(`quality groups, jumps and collapsing retain unsaved edits at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1440 ? 1060 : 844 });
    const errors: string[] = [], writes: unknown[] = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    const segment = (id: string, translatable = true) => ({ block_id: id, version: 1, translatable,
      source_text: `Original paragraph ${id}: 64 cores.`, target_inline: [{ type: 'text', text: '译文：32 个核心。' }],
      source_hash: 's', context_hash: 'c', review_status: 'not_reviewed' });
    const draft: any = { id: 'navigation', document_id: 'doc', edition_id: 'edition', generation: 1,
      target_locale: 'zh-Hans', segments: [segment('b88'), segment('b118'), segment('b142'), segment('figure', false)],
      qa: { id: 'qa', generation: 1, fingerprint: 'qa', valid: false, stale: false, issues: [
        { code: 'NUMBER_MISMATCH', severity: 'hard', block_id: 'b88', evidence: {
          source: '64 cores.', target: '32 个核心。', missing_from_target: [{ value: '64', unit: '', count: 1 }],
          extra_in_target: [{ value: '32', unit: '', count: 1 }] } },
        { code: 'SEMANTIC_RISK', severity: 'high', block_id: 'b118', fingerprint: 'risk' },
        { code: 'ASSET_MISSING', severity: 'hard', block_id: 'figure' },
        { code: 'DOCUMENT_STRUCTURE', severity: 'hard' },
      ] } };
    await page.route('**/api/v1/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname.slice('/api/v1'.length);
      if (path.endsWith('/events')) return route.fulfill({ status: 204 });
      if (request.method() !== 'GET') writes.push({ path, body: request.postDataJSON() });
      if (path === '/drafts/navigation/segments/b142' && request.method() === 'PATCH') {
        expect(request.postDataJSON()).toEqual({ target_inline: [{ type: 'text', text: '尚未保存的本地修订' }], reason: '保留测试', base_segment_version: 1 });
        draft.segments[2].target_inline = request.postDataJSON().target_inline;
        draft.segments[2].version = 2; draft.generation = 2; draft.qa.stale = true;
      }
      const data = path.startsWith('/drafts/navigation') ? draft : ({
        '/documents/doc': { id: 'doc', title: 'Quality navigation', editions: [] },
        '/settings/provider': { configured: false, cost_control_enabled: false },
        '/settings/preferences': { generation: 1, theme: width === 1440 ? 'dark' : 'light' },
      } as Record<string, unknown>)[path] ?? { items: [] };
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ETag: '"1"' }, body: JSON.stringify(data) });
    });
    await page.goto('/#/drafts/navigation');
    await expect(page.getByRole('heading', { name: '译文编辑' })).toBeVisible();
    const blocker = page.locator('#segment-b88'), risk = page.locator('#segment-b118'), ordinary = page.locator('#segment-b142');
    await expect(blocker.getByRole('button', { name: '折叠段落 b88' })).toHaveAttribute('aria-expanded', 'true');
    await expect(blocker).toContainText('有重要提示');
    await expect(blocker).not.toContainText('可选');
    await expect(risk.getByRole('button', { name: '展开段落 b118' })).toHaveAttribute('aria-expanded', 'false');
    await expect(ordinary.getByRole('textbox', { name: '译文文本 1' })).toBeHidden();
    await expect(page.getByRole('region', { name: '重要提示' })).toContainText('译文缺少：64（1 次）');
    await expect(page.getByRole('region', { name: '重要提示' })).toContainText('译文多出：32（1 次）');
    await expect(page.getByText('文档级提示', { exact: true })).toBeVisible();
    await page.getByLabel('问题筛选').selectOption('risks');
    await expect(page.getByRole('region', { name: '重要提示' })).toHaveCount(0);
    await expect(page.locator('.issue:visible')).toHaveCount(1);
    await page.getByRole('button', { name: '跳转段落 b118' }).click();
    await expect(risk).toBeFocused();
    await expect(risk.getByText('人工核对（可选）', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '展开段落 b142', exact: true }).click();
    await ordinary.getByRole('textbox', { name: '译文文本 1' }).fill('尚未保存的本地修订');
    await ordinary.getByLabel('修改理由').fill('保留测试');
    await page.getByRole('button', { name: '折叠段落 b142', exact: true }).click();
    await expect(ordinary.getByText('有未保存修改', { exact: true })).toBeVisible();
    await page.getByRole('combobox', { name: '显示', exact: true }).selectOption('selected');
    await expect(ordinary).toBeHidden();
    await page.getByRole('button', { name: '跳转段落 b118' }).click();
    await expect(page.getByRole('combobox', { name: '显示', exact: true })).toHaveValue('all');
    await page.getByRole('button', { name: '展开段落 b142', exact: true }).click();
    await expect(ordinary.getByRole('textbox', { name: '译文文本 1' })).toHaveValue('尚未保存的本地修订');
    await expect(ordinary.getByLabel('修改理由')).toHaveValue('保留测试');
    await expect(page.getByRole('button', { name: '运行质量检查', exact: true })).toBeDisabled();
    await page.getByLabel('问题筛选').selectOption('blockers');
    await expect(page.locator('.issue:visible')).toHaveCount(3);
    await page.getByRole('button', { name: '跳转段落 figure' }).click();
    await expect(page.locator('#segment-figure')).toBeFocused();
    await expect(page.locator('#segment-figure')).toContainText('本段保留原文');
    await page.getByRole('button', { name: '展开全部段落', exact: true }).click();
    await expect(risk.getByRole('button', { name: '折叠段落 b118' })).toBeVisible();
    await page.getByRole('button', { name: '折叠无重要提示的段落', exact: true }).click();
    await expect(ordinary.getByRole('textbox', { name: '译文文本 1' })).toBeHidden();
    await expect(blocker.getByRole('textbox', { name: '译文文本 1' })).toBeVisible();
    await page.getByLabel('问题筛选').selectOption('all');
    await page.getByText('一般提示 · 1', { exact: true }).click();
    await page.getByRole('region', { name: '质量问题', exact: true }).scrollIntoViewIfNeeded();
    expect(await page.title()).toBeTruthy();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    await page.screenshot({ path: resolve(outputDirectory('quality-navigation'), `groups-${width}.png`), fullPage: true });
    expect(writes).toEqual([]);
    await page.getByRole('button', { name: '展开段落 b142', exact: true }).click();
    await ordinary.getByRole('button', { name: '保存译文', exact: true }).click();
    await expect(ordinary.getByText('有未保存修改', { exact: true })).toHaveCount(0);
    await expect(blocker).toContainText('重要提示 · 待更新');
    expect(writes).toHaveLength(1);
    expect(errors).toEqual([]);
  });
}
