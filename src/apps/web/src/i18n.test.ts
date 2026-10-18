import { afterEach, describe, expect, it } from 'vitest';
import ts from 'typescript';
import { getUiLocale, messages, resolveUiLocale, setUiLocale, t } from './i18n';
import { statusLabel } from './domain';
import { errorMessage } from './messages';
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
          if (key && ts.isStringLiteral(key) && /[\u3400-\u9fff]/.test(key.text) && !messages[key.text]) missing.push(`${path}: ${key.text}`);
        }
        ts.forEachChild(node, visit);
      }
      visit(ast);
    }
    expect(missing).toEqual([]);
  });
});
