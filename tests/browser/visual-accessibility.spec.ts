import { test, expect, type Page } from '../../src/apps/web/node_modules/@playwright/test/index.mjs';
import { writeFileSync } from 'node:fs';
import { outputDirectory } from './paths';

async function fixture(page: Page, theme: string) {
  const errors: string[] = [], writes: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.slice(7);
    if (route.request().method() !== 'GET') writes.push(path);
    const values: Record<string, unknown> = {
      '/settings/preferences': { generation: 1, locale: 'zh-Hans', theme, parser_profile_revision: 'surya-ocr-2-v1' },
      '/settings/provider': { generation: 1, configured: true, has_api_key: false, provider: 'openai', api_protocol: 'responses', auth_mode: 'none', endpoint: 'https://synthetic.invalid/v1/responses', model_id: 'synthetic-model', cost_control_enabled: false },
      '/settings/dispatch': { generation: 1, dispatch_disabled: false },
      '/settings/parser-environment': { online: true, default: 'dmr', options: [{ id: 'dmr', profiles: ['surya-ocr-2-v1'] }] },
      '/settings/parser-models': { models: [{ id: 'surya-ocr-2-v1', label: 'Surya OCR 2', model_id: 'synthetic/parser', status: 'not_downloaded', download_bytes: 1000000 }] },
      '/settings/resources': { waiting_jobs: [], model_references: [] }, '/settings/local-models': { models: [] },
      '/documents': { items: [], total: 0 },
    };
    return route.fulfill({ json: values[path] ?? {}, headers: { ETag: '"1"' } });
  });
  await page.goto('/#/settings');
  await expect(page.getByRole('heading', { name: 'AI 服务', exact: true })).toBeVisible();
  return { errors, writes };
}

async function measure(page: Page) {
  return page.evaluate(() => {
    const ctx = document.createElement('canvas').getContext('2d')!;
    function rgba(color: string) { ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1); return [...ctx.getImageData(0, 0, 1, 1).data].map((x, i) => i === 3 ? x / 255 : x); }
    const mix = (front: number[], back: number[]) => front.slice(0, 3).map((v, i) => v * front[3] + back[i] * (1 - front[3]));
    function background(el: Element): number[] { const chain: Element[] = []; for (let node: Element | null = el; node; node = node.parentElement) chain.unshift(node); return chain.reduce((back, node) => mix(rgba(getComputedStyle(node).backgroundColor), back), [255, 255, 255]); }
    const luminance = (rgb: number[]) => rgb.slice(0, 3).map(x => x / 255).map(x => x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4).reduce((sum, x, i) => sum + x * [.2126, .7152, .0722][i], 0);
    const contrast = (a: number[], b: number[]) => { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
    const visible = (el: Element) => el instanceof HTMLElement && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && el.getBoundingClientRect().width > 0;
    const texts = [...document.querySelectorAll('.main *, .topbar *, .sidebar *')].filter(el => visible(el) && !el.closest(':disabled') && [...el.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.textContent?.trim())).map(el => {
      const style = getComputedStyle(el), bg = background(el), fg = mix(rgba(style.color), bg);
      const large = parseFloat(style.fontSize) >= 24 || parseFloat(style.fontSize) >= 18.6667 && parseFloat(style.fontWeight) >= 700;
      return { text: el.textContent?.trim().slice(0, 70), selector: `${el.tagName.toLowerCase()}.${el.className}`, color: style.color, background: bg, ratio: contrast(fg, bg), minimum: large ? 3 : 4.5 };
    });
    const controls = [...document.querySelectorAll('button, a[href], select, input, textarea, summary')].filter(el => visible(el) && !el.matches(':disabled')).map(el => {
      const target = el.matches('input[type=checkbox],input[type=radio]') ? el.closest('label') ?? el : el;
      const rect = target.getBoundingClientRect();
      return { name: el.getAttribute('aria-label') || el.textContent?.trim().slice(0, 50) || el.id, tag: el.tagName, width: rect.width, height: rect.height, inline: el.matches('a') && getComputedStyle(el).display === 'inline' };
    });
    const root = getComputedStyle(document.documentElement);
    const palette = ['--muted', '--en', '--zh', '--accent', '--control-line'].flatMap(token => ['--paper', '--bg'].map(surface => ({ token, surface,
      ratio: contrast(rgba(root.getPropertyValue(token)), rgba(root.getPropertyValue(surface))) })));
    return { viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio }, scrollWidth: document.documentElement.scrollWidth, texts, controls, palette };
  });
}

for (const scenario of [
  { name: 'light-desktop', theme: 'light', colorScheme: 'light', width: 1440 },
  { name: 'dark-mobile', theme: 'dark', colorScheme: 'light', width: 390 },
  { name: 'system-dark-320', theme: 'system', colorScheme: 'dark', width: 320 },
  { name: 'system-light-zoom-reflow', theme: 'system', colorScheme: 'light', width: 720 },
] as const) test(`measured management contrast, targets and reflow: ${scenario.name}`, async ({ page }) => {
  await page.setViewportSize({ width: scenario.width, height: 900 });
  if (scenario.name === 'system-light-zoom-reflow') {
    const cdp = await page.context().newCDPSession(page);
    // A 1440px-wide display at 200% browser zoom has a 720 CSS-pixel viewport.
    // Device emulation exercises that geometry; it is not a native browser zoom check.
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 720, height: 450, deviceScaleFactor: 2, mobile: false });
  }
  await page.emulateMedia({ colorScheme: scenario.colorScheme });
  const state = await fixture(page, scenario.theme);
  await page.locator('#settings-parser .model-choice-details > summary').click();
  // Exercise an actual validation error in both themes without making a request.
  await page.getByLabel('解析超时（分钟）').fill('0');
  await expect(page.getByText('请输入 1–1440 之间的整数分钟。')).toBeVisible();
  const result = await measure(page);
  writeFileSync(outputDirectory(`measurements-${scenario.name}.json`), JSON.stringify(result, null, 2));
  expect(result.scrollWidth).toBeLessThanOrEqual(scenario.width + 1);
  expect(result.texts.filter(row => row.ratio < row.minimum)).toEqual([]);
  expect(result.palette.filter(row => !Number.isFinite(row.ratio) || row.ratio < (row.token === '--control-line' ? 3 : 4.5))).toEqual([]);
  expect(result.controls.filter(row => !row.inline && (row.width < 24 || row.height < 24))).toEqual([]);
  if (scenario.width <= 760) expect(result.controls.filter(row => ['BUTTON', 'SELECT', 'SUMMARY'].includes(row.tag) && row.height < 44)).toEqual([]);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: outputDirectory(`management-${scenario.name}.png`), fullPage: true });
  expect(state.errors).toEqual([]); expect(state.writes).toEqual([]);
});

test('200 percent text enlargement preserves controls and keyboard search focus', async ({ page }) => {
  const state = await fixture(page, 'light');
  // Text-only 200% stress test; viewport-reduction reflow is covered separately.
  await page.evaluate(() => {
    const styles = [...document.querySelectorAll<HTMLElement>('body *')].map(el => ({ el, size: getComputedStyle(el).fontSize, line: getComputedStyle(el).lineHeight }));
    for (const { el, size, line } of styles) { el.style.fontSize = `${parseFloat(size) * 2}px`; if (line.endsWith('px')) el.style.lineHeight = `${parseFloat(line) * 2}px`; }
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await expect(page.getByRole('button', { name: '保存 AI 服务配置', exact: true })).toBeVisible();
  await page.screenshot({ path: outputDirectory('management-text-200.png'), fullPage: true });
  await page.goto('/#/library');
  const search = page.getByRole('textbox', { name: '搜索标题' });
  await search.focus();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Shift+Tab');
  await expect(search).toBeFocused();
  expect(await page.locator('.searchbox').evaluate(el => getComputedStyle(el).outlineStyle)).toBe('solid');
  expect(state.errors).toEqual([]); expect(state.writes).toEqual([]);
});
