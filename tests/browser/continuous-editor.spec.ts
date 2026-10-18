import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { resolve } from 'node:path';
import { outputDirectory } from './paths';

for (const width of [1440, 390]) test(`continuous rich paragraph preserves semantic nodes at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
  const errors: string[] = [], writes: any[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const original = [{ type: 'text', text: 'Alpha ' }, { type: 'text', text: 'bold ', marks: ['strong'], output_path: 'body/0' },
    { type: 'link', text: 'link ', href: 'https://example.org', marks: ['emphasis'] },
    { type: 'xref', label: 'ref ', target_block_id: 'b2' }, { type: 'protected_ref', ref: 'n1' }, { type: 'text', text: ' omega' }];
  const draft: any = { id: 'rich', document_id: 'doc', edition_id: 'edition', source_revision_id: 'source', source_hash: 's', generation: 1,
    target_locale: 'zh-Hans', source: { protected_atoms: { n1: { value: '64' } } }, segments: [{ block_id: 'b1', source_text: 'An original paragraph.',
      target_inline: structuredClone(original), version: 1, source_hash: 's', context_hash: 'c', review_status: 'not_reviewed' }] };
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.slice('/api/v1'.length);
    if (request.method() !== 'GET') writes.push({ path, body: request.postDataJSON() });
    if (path === '/drafts/rich/segments/b1' && request.method() === 'PATCH') {
      draft.segments[0].target_inline = request.postDataJSON().target_inline;
      draft.segments[0].version++; draft.generation++;
    }
    const data = path === '/drafts/rich' || path === '/drafts/rich/segments/b1' ? draft
      : path === '/documents/doc' ? { id: 'doc', title: 'Rich paragraph', editions: [] }
      : path === '/settings/preferences' ? { generation: 1, theme: 'dark' }
      : path === '/settings/provider' ? { configured: false } : { items: [] };
    await route.fulfill({ contentType: 'application/json', headers: { ETag: `"${draft.generation}"` }, body: JSON.stringify(data) });
  });
  await page.goto('/#/drafts/rich');
  await expect(page.getByRole('heading', { name: '译文编辑', exact: true })).toBeVisible();
  const collapsed = page.getByRole('button', { name: '展开段落 b1', exact: true });
  if (await collapsed.count()) await collapsed.click();
  const editor = page.getByRole('textbox', { name: '译文段落', exact: true });
  await expect(editor).toHaveText('Alpha bold link ref 64 omega');
  await editor.focus();
  // Select across two ordinary runs, leaving semantic references untouched.
  await editor.evaluate(element => {
    const range = document.createRange(); range.setStart(element.children[0].firstChild!, 2); range.setEnd(element.children[1].firstChild!, 2);
    const selection = getSelection()!; selection.removeAllRanges(); selection.addRange(range);
  });
  await page.keyboard.insertText(' edited ');
  await expect(editor).toHaveText('Al edited ld link ref 64 omega');
  await page.keyboard.press('Control+z');
  await expect(editor).toHaveText('Alpha bold link ref 64 omega');
  await page.keyboard.press('Control+y');
  await expect(editor).toHaveText('Al edited ld link ref 64 omega');
  await editor.evaluate(element => {
    const atom = element.querySelector('[contenteditable="false"]')!;
    const range = document.createRange(); range.selectNode(atom);
    const selection = getSelection()!; selection.removeAllRanges(); selection.addRange(range);
  });
  await page.keyboard.press('Backspace');
  await expect(editor).toContainText('64');
  await expect(page.getByRole('status').filter({ hasText: '受保护' })).toBeVisible();
  await editor.focus(); await page.keyboard.press('Control+End');
  await editor.evaluate(element => {
    const clipboardData = new DataTransfer(); clipboardData.setData('text/plain', ' <script>literal</script>');
    element.dispatchEvent(new ClipboardEvent('paste', { clipboardData, bubbles: true, cancelable: true }));
  });
  await expect(editor).toContainText('<script>literal</script>');
  await expect(editor.locator('script')).toHaveCount(0);
  // IME composition is accepted once completed, not as a half-composed save.
  await editor.evaluate(element => {
    element.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
    element.lastChild!.textContent += '中文';
    element.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: true, inputType: 'insertCompositionText', data: '中文' }));
    element.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '中文' }));
  });
  await expect(editor).toContainText('中文');
  await page.getByLabel('修改理由', { exact: true }).fill('核对原段落后修正');
  await page.getByRole('button', { name: '保存译文', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  const saved = writes[0].body.target_inline;
  expect(saved[1]).toMatchObject({ type: 'text', marks: ['strong'], output_path: 'body/0' });
  expect(saved[2]).toEqual(original[2]); expect(saved[3]).toEqual(original[3]); expect(saved[4]).toEqual(original[4]);
  expect(writes[0].body.base_segment_version).toBe(1);
  await expect(page.getByText('有未保存修改', { exact: true })).toHaveCount(0);
  expect(await page.title()).toContain('对照文库');
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: resolve(outputDirectory('continuous-editor'), `rich-${width}.png`), fullPage: true });
  expect(errors).toEqual([]);
});
