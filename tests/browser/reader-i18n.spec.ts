import { test, expect } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { inputPath } from './paths';

const supplied = process.env.LIBRARY_READER_I18N_EVIDENCE;
const folder = supplied ? inputPath(supplied) : '';
const server = process.env.LIBRARY_READER_I18N_URL;
const themes = {
  'zh-Hans': '主题', 'zh-Hant': '主題', en: 'Theme', ja: 'テーマ', ko: '테마',
  fr: 'Thème', de: 'Design', es: 'Tema',
};
test.beforeEach(() => test.skip(!supplied || !server,
  'Generate reader_i18n_evidence.py fixtures and serve them on the explicit loopback URL.'));

for (const version of ['3.0', '4.0']) {
  for (const [locale, theme] of Object.entries(themes)) {
    test(`${version} ${locale} publication and offline controls use the translation language`, async ({ browser }, testInfo) => {
      const key = `${version}-${locale}`;
      const fixture = JSON.parse(readFileSync(resolve(folder, key, 'fixture.json'), 'utf8'));
      // Deliberately disagree with the artifact language in both browser and app preferences.
      const context = await browser.newContext({ locale: locale === 'zh-Hans' ? 'en-US' : 'zh-CN' });
      try {
        await context.addInitScript(() => {
          try { localStorage.setItem('paper-translation.ui-locale.v1', navigator.language.startsWith('en') ? 'en' : 'zh-Hans'); }
          catch (_) { /* file:// storage may be unavailable; reader must still work. */ }
        });
        const page = await context.newPage();
        const errors: string[] = [], outbound: string[] = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
        page.on('request', request => {
          if (/^https?:/.test(request.url()) && !request.url().startsWith(server + '/')) outbound.push(request.url());
        });
        for (const format of ['published/index.html', 'single.html', 'bundle/index.html']) {
          const online = format.startsWith('published/');
          await context.setOffline(!online);
          await page.setViewportSize({ width: 1440, height: 1060 });
          const url = online ? `${server}/artifacts/${key}/index.html`
            : pathToFileURL(resolve(folder, key, format)).href;
          await page.goto(url);
          expect(page.url()).toBe(url);
          await expect(page).toHaveTitle(fixture.target_title);
          await expect(page.locator('article')).toBeVisible();
          await expect(page.locator('vite-error-overlay')).toHaveCount(0);
          await expect(page.locator('html')).toHaveAttribute('lang', locale);
          const payload = JSON.parse(await page.locator('#reader-i18n-data').textContent() || '{}');
          expect(payload.locale).toBe(locale);
          const message = (source: string, values: Record<string, string> = {}) =>
            (payload.messages[source] ?? source).replace(/\{(\w+)\}/g,
              (match: string, name: string) => Object.hasOwn(values, name) ? values[name] : match);
          await expect(page.locator('header h1')).toHaveText(fixture.target_title);
          await expect(page.locator('header .original-title')).toHaveText(fixture.source_title);
          await expect(page.locator('header script')).toHaveCount(0);
          await expect(page.getByRole('combobox', { name: theme, exact: true })).toBeVisible();
          await expect(page.locator('.toolbar')).toHaveAccessibleName(message('阅读设置'));
          await expect(page.locator('[data-action="smaller"]')).toHaveAccessibleName(message('减小字号'));
          await expect(page.locator('[data-action="larger"]')).toHaveAccessibleName(message('增大字号'));
          await expect(page.locator('nav.toc-sections')).toHaveAccessibleName(message('双语章节'));
          await expect(page.locator('[data-action="source"]')).toHaveText(message('原文'));
          await expect(page.locator('[data-action="target"]')).toHaveText(message('译文'));
          await expect(page.locator('[data-online-reader]')).toHaveCount(online ? 1 : 0);
          if (!online) await expect(page.locator('a[href="original.pdf"]')).toHaveCount(0);
          if (['en', 'fr', 'de', 'es'].includes(locale)) {
            // Scope to authored controls; source text, translated paper content,
            // bibliography and bundled license documents are deliberately excluded.
            const controls = await page.locator('.toolbar, .reader-return, #reader-storage-notice, .reader-font-notice, .reader-font-notice > p, .reader-font-notice summary, .toc > h2').evaluateAll(nodes =>
              nodes.flatMap(node => [node.matches('.reader-font-notice')
                ? Array.from(node.childNodes).filter(child => child.nodeType === Node.TEXT_NODE).map(child => child.textContent).join('')
                : node.textContent || '', ...Array.from(node.querySelectorAll('*')).flatMap(child =>
                ['aria-label', 'title', 'placeholder', 'alt'].map(attribute => child.getAttribute(attribute) || ''))]));
            expect(controls.filter(value => /\p{Script=Han}/u.test(value))).toEqual([]);
          }

          const themeSelect = page.getByRole('combobox', { name: theme, exact: true });
          await themeSelect.selectOption('dark');
          await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
          const font = page.locator('[data-font-select]');
          await font.selectOption('serif');
          const selectedFont = await font.locator('option:checked').textContent() || '';
          await expect(font).toHaveAttribute('title', message('{font} · 使用本机字体；未安装时使用备用字体。', { font: selectedFont }));
          await page.locator('[data-action="source"]').click();
          await expect(page.locator('header h1')).toBeHidden();
          await page.locator('[data-action="both"]').click();
          await expect(page.locator('header h1')).toBeVisible();

          const citation = page.locator('a[data-reference-targets]').first();
          const citationText = await citation.textContent() || '';
          await citation.click();
          const panel = page.getByRole('region', { name: message('参考文献详情'), exact: true });
          await expect(panel).toBeVisible();
          await expect(panel.locator('.sidenote-heading > span')).toHaveText(message('参考文献 · {citation}', { citation: citationText }));
          await expect(panel.getByRole('link', { name: message('在参考文献列表中查看'), exact: true }).first()).toBeVisible();
          await panel.getByRole('button', { name: message('关闭参考文献'), exact: true }).click();
          await expect(panel).toBeHidden();
          await expect(citation).toBeFocused();

          if (version === '4.0' && format === 'single.html') {
            await page.keyboard.press('Control+Home');
            await page.screenshot({ path: testInfo.outputPath(`${locale}-desktop.png`) });
          }
          await page.setViewportSize({ width: 390, height: 844 });
          await page.keyboard.press('Control+Home');
          await expect(themeSelect).toBeVisible();
          expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
          await themeSelect.focus();
          await expect(themeSelect).toBeFocused();
          if (version === '4.0' && format === 'single.html') {
            await page.screenshot({ path: testInfo.outputPath(`${locale}-mobile.png`) });
          }
          await page.reload();
          await expect(page.locator('html')).toHaveAttribute('lang', locale);
          await expect(themeSelect).toHaveValue('dark');
          await expect(page.locator('header h1')).toHaveText(fixture.target_title);
        }
        expect(errors).toEqual([]);
        expect(outbound).toEqual([]);
      } finally { await context.close(); }
    });
  }
}

for (const [locale, theme] of Object.entries(themes)) {
  test(`${locale} static labels survive without JavaScript`, async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false, locale: 'en-US' });
    try {
      const page = await context.newPage();
      for (const format of ['single.html', 'bundle/index.html']) {
        await context.setOffline(true);
        await page.goto(pathToFileURL(resolve(folder, `4.0-${locale}`, format)).href);
        await expect(page.locator('html')).toHaveAttribute('lang', locale);
        await expect(page.getByRole('combobox', { name: theme, exact: true })).toBeVisible();
        await expect(page.locator('article')).toBeVisible();
        await expect(page.locator('[data-online-reader]')).toHaveCount(0);
      }
    } finally { await context.close(); }
  });

  test(`${locale} unavailable storage and formula rendering use localized notices`, async ({ browser }) => {
    const context = await browser.newContext({ locale: 'en-US', offline: true });
    try {
      await context.addInitScript(() => {
        Storage.prototype.getItem = () => { throw new Error('Storage disabled by test'); };
        Storage.prototype.setItem = () => { throw new Error('Storage disabled by test'); };
        Object.defineProperty(window, 'katex', {
          configurable: true, get: () => ({ render: () => { throw new Error('Formula test fallback'); } }), set: () => {},
        });
        // The authored navigation fixture keeps its displayed formula as a PDF
        // crop. Add a formula before the reader's DOMContentLoaded handler to
        // exercise its separately localized JavaScript failure path.
        document.addEventListener('DOMContentLoaded', () => {
          const formula = document.createElement('span');
          formula.dataset.tex = 'x + y';
          formula.textContent = 'x + y';
          document.body.append(formula);
        }, { once: true });
      });
      const page = await context.newPage();
      await page.goto(pathToFileURL(resolve(folder, `3.0-${locale}`, 'single.html')).href);
      const payload = JSON.parse(await page.locator('#reader-i18n-data').textContent() || '{}');
      const message = (source: string) => payload.messages[source] ?? source;
      const notice = page.locator('#reader-storage-notice');
      await expect(notice).toBeVisible();
      await expect(notice).toHaveText(message('浏览器存储不可用；正文仍可完整阅读。'));
      await expect(page.locator('[data-tex].math-error').first()).toHaveAttribute('title', message('此公式暂不能排版，保留识别文字供原文对照。'));
      await page.getByRole('combobox', { name: theme, exact: true }).selectOption('light');
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
      await expect(page.locator('html')).toHaveAttribute('lang', locale);
    } finally { await context.close(); }
  });
}
