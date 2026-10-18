import { afterEach, describe, expect, it } from 'vitest';
import ts from 'typescript';
import { getUiLocale, messages, resolveUiLocale, setUiLocale, t } from './i18n';
import { statusLabel } from './domain';
import { errorMessage, issueMessage } from './messages';
import { localizeBootstrap } from './bootstrap-i18n';
import { coreMessages } from './locales/core';
import { settingsMessages } from './locales/settings';
import { workflowMessages } from './locales/workflow';
import { editorMessages } from './locales/editor';

afterEach(() => setUiLocale('zh-Hans'));
describe('interface language', () => {
  it('resolves script and region while respecting the browser preference order', () => {
    expect(resolveUiLocale(['zh-TW'])).toBe('zh-Hant');
    expect(resolveUiLocale(['zh-HK'])).toBe('zh-Hant');
    expect(resolveUiLocale(['zh-Hans-TW'])).toBe('zh-Hans');
    expect(resolveUiLocale(['zh-CN'])).toBe('zh-Hans');
    expect(resolveUiLocale(['en-AU', 'zh-Hant'])).toBe('en');
    expect(resolveUiLocale(['fr', 'zh-Hant'])).toBe('zh-Hant');
    expect(resolveUiLocale(['invalid_!', 'de'])).toBe('en');
  });
  it('switches display-time status and error maps without changing their identifiers', () => {
    setUiLocale('en');
    expect(statusLabel('queued')).toBe('Queued');
    expect(errorMessage('BUDGET_REQUIRED')).toMatch(/budget/i);
    expect(errorMessage('UNKNOWN_BACKEND', '无法识别的原始诊断')).toBe('The operation did not complete. Review the technical details or try again later.');
    setUiLocale('zh-Hant');
    expect(statusLabel('queued')).toBe('排隊中');
    expect(t('界面语言')).toBe('介面語言');
    expect(getUiLocale()).toBe('zh-Hant');
  });
  it('interpolates only named values once and preserves their contents', () => {
    setUiLocale('en');
    expect(t('跳转段落 {id}', { id: '<b>设置</b> {id} $&' })).toBe('Go to segment <b>设置</b> {id} $&');
    expect(t('unregistered {value}', { value: 0 })).toBe('unregistered 0');
    expect(t('unregistered {missing}', {})).toBe('unregistered {missing}');
  });
  it('localizes authored source diagnostics and preserves model explanations and evidence', () => {
    const issue = { stage: 'source_check', category: 'page_missing', page: 2, severity: 'important', message: '第 2 页文字未完整提取' };
    setUiLocale('en'); expect(issueMessage(issue)).toBe('Text on page 2 was not fully extracted');
    expect(issueMessage({ stage: 'translation', severity: 'important', code: 'NUMBER_MISMATCH', message: '译文中的数字与原文存在差异，可查看原 PDF 对照。' })).toContain('Numbers differ');
    setUiLocale('zh-Hant'); expect(issueMessage(issue)).toBe('第 2 頁文字未完整擷取');
    expect(issueMessage({ stage: 'semantic_review', severity: 'info', message: '设置 <paper> body' })).toBe('设置 <paper> body');
    expect(issue.message).toBe('第 2 页文字未完整提取');
  });
  it('builds the no-JavaScript notice from all three catalog languages', () => {
    const page = localizeBootstrap('<title><!--app-title--></title><noscript><!--app-noscript--></noscript>');
    expect(page).toContain('<title>Bilingual Library · Personal PDF library</title>');
    expect(page).toContain('<p lang="en">The management interface requires JavaScript.');
    expect(page).toContain('<p lang="zh-Hans">管理界面需要 JavaScript。');
    expect(page).toContain('<p lang="zh-Hant">管理介面需要 JavaScript。');
    expect(page).not.toContain('<!--app-');
  });
  it('keeps every catalogue translation and interpolation complete', () => {
    const keys = [coreMessages, settingsMessages, workflowMessages, editorMessages].flatMap(catalog => Object.keys(catalog));
    expect(new Set(keys).size, 'Shared messages must be declared only in core.ts').toBe(keys.length);
    const placeholders = (text: string) => [...new Set(text.match(/\{\w+\}/g) ?? [])].sort();
    for (const [source, translations] of Object.entries(messages)) {
      for (const translation of translations) {
        expect(translation.trim(), source).not.toBe('');
        expect(placeholders(translation), source).toEqual(placeholders(source));
      }
    }
  });
  it('provides both translations for every explicit UI message', () => {
    const files = import.meta.glob(['./**/*.ts', './**/*.tsx', '!./**/*.test.ts', '!./locales/**'], { query: '?raw', import: 'default', eager: true });
    const missing: string[] = [];
    for (const [path, source] of Object.entries(files)) {
      const ast = ts.createSourceFile(path, source as string, ts.ScriptTarget.Latest, true, path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
      function visit(node: ts.Node) {
        if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 't') {
          const key = node.arguments[0];
          if (key && ts.isStringLiteralLike(key) && !messages[key.text]) missing.push(`${path}: ${key.text}`);
        }
        ts.forEachChild(node, visit);
      }
      visit(ast);
    }
    expect(missing).toEqual([]);
  });
});
