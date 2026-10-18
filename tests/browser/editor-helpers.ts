import { expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';

/** Expand optional tools when a regression is testing their underlying contract. */
export async function openEditorTools(page: Page) {
  await expect(page.getByRole('heading', { name: '译文编辑', exact: true })).toBeVisible();
  for (const label of ['检查与版本', '翻译依据与原文']) {
    const summary = page.getByText(label, { exact: true });
    if (!(await summary.evaluate(element => element.parentElement!.hasAttribute('open')))) await summary.click();
  }
  const batch = page.locator('.editor-tool-group > summary').filter({ hasText: '批量处理' });
  if (!(await batch.evaluate(element => element.parentElement!.hasAttribute('open')))) await batch.click();
  for (const selector of ['.editor-check-results', '.editor-candidate-results']) {
    const details = page.locator(selector);
    if (await details.count() && !(await details.getAttribute('open') !== null)) await details.locator(':scope > summary').click();
  }
}
