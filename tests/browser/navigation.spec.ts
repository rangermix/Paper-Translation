import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';

test('keyboard skip link focuses current content without changing the route', async ({ page }) => {
  await page.route('**/api/v1/**', route => route.fulfill({ json:
    new URL(route.request().url()).pathname.endsWith('/settings/preferences')
      ? { locale: 'zh-Hans', publish_policy: 'auto_publish', theme: 'light' } : { items: [] },
  }));
  await page.goto('/#/upload');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: '跳到主要内容' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#\/upload$/);
  await expect(page.getByRole('main')).toBeFocused();
  await expect(page.getByRole('heading', { name: '上传 PDF', exact: true })).toBeVisible();
});
