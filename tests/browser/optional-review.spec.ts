import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { outputDirectory } from './paths';
import { resolve } from 'node:path';

for (const viewport of [{ width: 1440, height: 1060 }, { width: 390, height: 844 }]) {
  test(`unreviewed draft can validate, seal and publish with advisory risk at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const writes: string[] = [], errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    const draft: any = { id: 'optional', document_id: 'doc', edition_id: 'edition', source_revision_id: 'source',
      source_hash: 'a'.repeat(64), generation: 1, target_locale: 'zh-Hans', glossary_revision: 'empty-v1',
      segments: [{ block_id: 'p1', version: 1, source_hash: 'b'.repeat(64), context_hash: 'c'.repeat(64),
        source_text: 'Only keep the original. Do not change the source.', target_inline: [{ type: 'text', text: '只保留原件。不要更改原文。' }],
        review_status: 'not_reviewed', translatable: true }], qa: null };
    const issue = { code: 'SEMANTIC_RISK', severity: 'high', block_id: 'p1', fingerprint: 'risk', resolved: false };
    await page.route('**/api/v1/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname.slice('/api/v1'.length);
      if (path.endsWith('/events')) return route.fulfill({ status: 204 });
      if (request.method() !== 'GET') writes.push(path);
      let response: any;
      if (path === '/drafts/optional/validate') {
        draft.qa = { id: 'qa', generation: 1, fingerprint: 'qa-fingerprint', valid: true, stale: false, issues: [issue] };
        response = draft.qa;
      } else if (path === '/drafts/optional/seal') {
        expect(request.postDataJSON()).toEqual({ qa_id: 'qa', qa_fingerprint: 'qa-fingerprint', generation: 1 });
        response = { translation_revision_id: 'revision' };
      } else if (path === '/editions/edition/publish') {
        expect(request.postDataJSON().translation_revision_id).toBe('revision');
        response = { job_id: 'publication' };
      } else response = ({
        '/drafts/optional': draft,
        '/documents/doc': { id: 'doc', title: 'Optional review', tags: [], generation: 1, editions: [{ id: 'edition', target_locale: 'zh-Hans', generation: 1 }] },
        '/settings/provider': { configured: false, cost_control_enabled: false },
        '/settings/preferences': { generation: 1, theme: 'light' },
        '/capabilities': { source_mime_types: ['application/pdf'], limits: {} },
        '/jobs/publication': { id: 'publication', title: 'Optional review', status: 'pending', stage: 'build', generation: 1 },
      } as Record<string, unknown>)[path] ?? { items: [] };
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { ETag: '"1"' }, body: JSON.stringify(response) });
    });
    await page.goto('/#/drafts/optional');
    await expect(page).toHaveURL(/#\/drafts\/optional$/);
    expect(await page.title()).toBeTruthy();
    await expect(page.getByRole('heading', { name: '译文编辑' })).toBeVisible();
    await expect(page.getByText('未核对 · 可选', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: '展开段落 p1', exact: true }).click();
    await expect(page.getByText('人工核对（可选）', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '封存当前修订' })).toBeEnabled();
    await page.getByRole('button', { name: '运行质量检查', exact: true }).click();
    await expect(page.getByRole('button', { name: '封存当前修订' })).toBeEnabled();
    await page.getByText('一般提示 · 1', { exact: true }).click();
    await expect(page.locator('.issue')).toContainText('SEMANTIC_RISK');
    await page.getByText('人工核对（可选）', { exact: true }).click();
    await expect(page.getByText(/无需人工确认即可封存和发布/)).toBeVisible();
    await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: resolve(outputDirectory('optional-review'), `review-${viewport.width}.png`), fullPage: true });
    await page.getByRole('button', { name: '封存当前修订' }).click();
    await page.getByRole('button', { name: '构建并发布封存版' }).click();
    await expect(page).toHaveURL(/#\/jobs\/publication$/);
    expect(writes).toEqual(['/drafts/optional/validate', '/drafts/optional/seal', '/editions/edition/publish']);
    expect(errors).toEqual([]);
  });
}

for (const state of ['stale', 'hard']) {
  test(`${state} QA allows sealing with automatic refresh and no required review`, async ({ page }) => {
    const draft = { id: 'blocked', document_id: 'doc', edition_id: 'edition', generation: 1, target_locale: 'zh-Hans', segments: [],
      qa: { id: 'qa', generation: 1, fingerprint: 'qa', stale: state === 'stale', valid: state === 'stale',
        issues: state === 'hard' ? [{ code: 'MISSING_TRANSLATION', severity: 'hard', block_id: 'p1' }] : [] } };
    await page.route('**/api/v1/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(
      route.request().url().includes('/drafts/blocked') ? draft : { id: 'doc', title: 'Blocked fixture', editions: [], items: [] }) }));
    await page.goto('/#/drafts/blocked');
    await expect(page.getByText(state === 'stale' ? '质量报告已过期' : '当前版本有内容提示', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '封存当前修订' })).toBeEnabled();
    await expect(page.getByRole('button', { name: '运行质量检查', exact: true })).toBeEnabled();
  });
}
