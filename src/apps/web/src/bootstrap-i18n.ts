import { coreMessages } from './locales/core';

const title = '对照文库 · 个人 PDF 知识库';
const noScript = '管理界面需要 JavaScript。已发布的静态阅读页面不需要 JavaScript 即可阅读完整正文。';
const escapeHtml = (value: string) => value.replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]!);

/** Build-time fallback: without JavaScript there is no browser-language negotiation. */
export function localizeBootstrap(html: string): string {
  const alternatives = [
    ['en', coreMessages[noScript][0]], ['zh-Hans', noScript], ['zh-Hant', coreMessages[noScript][1]],
  ];
  return html.replace('<!--app-title-->', escapeHtml(coreMessages[title][0]))
    .replace('<!--app-noscript-->', alternatives.map(([locale, text]) => `<p lang="${locale}">${escapeHtml(text)}</p>`).join(''));
}
