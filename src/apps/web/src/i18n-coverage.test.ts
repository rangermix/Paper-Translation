import { describe, expect, it } from 'vitest';
import ts from 'typescript';
import { messages } from './i18n';

// Exceptions are exact values in named files, never entire components or languages.
// They are identities/data formats, not application instructions or status text.
const literalExceptions: Record<string, Record<string, string>> = {
  './features/history.tsx': { '· reader-v15': 'Immutable template identifier.' },
  './features/bibliography.tsx': { DOI: 'Identifier standard.', Crossref: 'Metadata provider name.', 'DOI Citation Formatter': 'External service name.' },
  './features/library.tsx': { MiB: 'Binary size unit.', 'SHA-256': 'Hash algorithm name.' },
  './features/local-models.tsx': { GGUF: 'Model format name.', MLX: 'Backend name.', Safetensors: 'Model format name.' },
  './features/parser-select.tsx': { 'GPU：': 'Hardware identifier.', 'Surya OCR 2': 'Model identity.', 'Chandra OCR 2': 'Model identity.', 'Infinity-Parser2 Pro': 'Model identity.', 'Infinity-Parser2 Flash': 'Model identity.' },
  './features/provider-connection.tsx': { USD: 'Currency code.' },
  './features/provider-settings.tsx': { token: 'Token accounting unit.' },
  './features/resource-settings.tsx': { RAM: 'Hardware identifier.' },
  './features/translation-preparation.tsx': { bit: 'Quantization unit.' },
  './features/upload-metadata.tsx': { 'Crossref ·': 'Metadata provider name.' },
  './features/upload.tsx': { KiB: 'Binary size unit.' },
};
const textAttributes = new Set(['title', 'placeholder', 'alt', 'aria-label', 'aria-description', 'aria-valuetext', 'label', 'description', 'data-label']);
const hasWords = (value: string) => /\p{L}/u.test(value);
const dataLiteralExceptions: Record<string, Record<string, string>> = {
  './domain.ts': { '保护内容': 'Legacy malformed-inline sentinel; changing its text changes content/selection offsets.' },
  './features/inline-editing.ts': { '保护内容': 'Same stable malformed-inline sentinel as domain.inlineText; accessibility labels are localized separately.' },
};

/** Inspect text-producing expressions, not event handlers, routing IDs or user data. */
function auditUi(files: Record<string, string>, exceptions = literalExceptions) {
  const sources = new Map(Object.entries(files).filter(([path]) => /\.[tj]sx?$/.test(path)).map(([path, source]) =>
    [path.replace(/^\.\//, ''), ts.createSourceFile(path.replace(/^\.\//, ''), source, ts.ScriptTarget.Latest, true, path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)]));
  const host: ts.CompilerHost = {
    getSourceFile: path => sources.get(path), getDefaultLibFileName: () => '', writeFile: () => {},
    getCurrentDirectory: () => '', getDirectories: () => [], fileExists: path => sources.has(path),
    readFile: path => files[`./${path}`], getCanonicalFileName: path => path, useCaseSensitiveFileNames: () => true, getNewLine: () => '\n',
  };
  const program = ts.createProgram([...sources.keys()], { noLib: true, noResolve: true, allowJs: true, jsx: ts.JsxEmit.Preserve }, host);
  const checker = program.getTypeChecker();
  const failures = new Set<string>();
  for (const [sourcePath, source] of sources) {
    const path = `./${sourcePath}`;
    function report(node: ts.Node, value: string) {
      const text = value.trim();
      if (!hasWords(text) || exceptions[path]?.[text]) return;
      const { line } = source.getLineAndCharacterOfPosition(node.getStart(source));
      failures.add(`${path}:${line + 1}: ${text}`);
    }
    function members(node: ts.Node | undefined, key: string | undefined, seen: Set<ts.Node>): ts.Node[] {
      if (!node || seen.has(node)) return [];
      seen = new Set(seen).add(node);
      if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node)) return members(node.expression, key, seen);
      if (ts.isArrayLiteralExpression(node)) return node.elements.flatMap(element => members(element, key, seen));
      if (ts.isObjectLiteralExpression(node)) return node.properties.flatMap(property => ts.isPropertyAssignment(property) &&
        (key === undefined || property.name.getText(source).replace(/^['"]|['"]$/g, '') === key) ? [property.initializer] : []);
      if (ts.isIdentifier(node)) return (checker.getSymbolAtLocation(node)?.declarations ?? []).flatMap(declaration => {
        if (ts.isVariableDeclaration(declaration)) return members(declaration.initializer, key, seen);
        if (ts.isParameter(declaration) && ts.isArrowFunction(declaration.parent)) {
          const call = declaration.parent.parent;
          if (ts.isCallExpression(call) && ts.isPropertyAccessExpression(call.expression) && call.expression.name.text === 'map') {
            return members(call.expression.expression, key, seen);
          }
        }
        return [];
      });
      return [];
    }
    function inspect(node: ts.Node | undefined, seen = new Set<ts.Node>()) {
      if (!node || seen.has(node)) return;
      seen = new Set(seen).add(node);
      if (ts.isStringLiteralLike(node) || ts.isJsxText(node)) return report(node, node.text);
      if (ts.isJsxExpression(node)) return inspect(node.expression, seen);
      if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isNonNullExpression(node)) return inspect(node.expression, seen);
      if (ts.isConditionalExpression(node)) { inspect(node.whenTrue, seen); inspect(node.whenFalse, seen); return; }
      if (ts.isBinaryExpression(node)) {
        if (node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) inspect(node.right, seen);
        else if ([ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken, ts.SyntaxKind.PlusToken].includes(node.operatorToken.kind)) {
          inspect(node.left, seen); inspect(node.right, seen);
        }
        return;
      }
      if (ts.isTemplateExpression(node)) {
        report(node.head, node.head.text);
        node.templateSpans.forEach(span => { report(span.literal, span.literal.text); inspect(span.expression, seen); });
        return;
      }
      if (ts.isIdentifier(node)) {
        checker.getSymbolAtLocation(node)?.declarations?.forEach(declaration => {
          if (ts.isVariableDeclaration(declaration)) inspect(declaration.initializer, seen);
          if (ts.isParameter(declaration) || ts.isBindingElement(declaration)) inspect(declaration.initializer, seen);
        });
        return;
      }
      if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
        const key = ts.isPropertyAccessExpression(node) ? node.name.text :
          ts.isStringLiteralLike(node.argumentExpression) ? node.argumentExpression.text : undefined;
        members(node.expression, key, new Set()).forEach(value => inspect(value, seen));
        return;
      }
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && !['t', 'readerTranslate'].includes(node.expression.text)) {
        checker.getSymbolAtLocation(node.expression)?.declarations?.forEach(declaration => {
          if (!ts.isFunctionDeclaration(declaration) || !declaration.body) return;
          const returns = (child: ts.Node) => {
            if (ts.isReturnStatement(child)) inspect(child.expression, seen);
            else if (!ts.isFunctionLike(child)) ts.forEachChild(child, returns);
          };
          returns(declaration.body);
        });
      }
    }
    function visit(node: ts.Node) {
      if (ts.isJsxText(node)) inspect(node);
      if (ts.isJsxExpression(node) && !ts.isJsxAttribute(node.parent)) inspect(node.expression);
      if (ts.isJsxAttribute(node) && textAttributes.has(node.name.getText(source))) inspect(node.initializer);
      // Also covers imperatively authored titles, native validation text and dialogs.
      if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
          ts.isPropertyAccessExpression(node.left) && ['title', 'textContent', 'innerText'].includes(node.left.name.text)) inspect(node.right);
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) &&
          ['setCustomValidity', 'alert', 'confirm', 'prompt'].includes(node.expression.name.text)) inspect(node.arguments[0]);
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'setAttribute' &&
          node.arguments[0] && ts.isStringLiteralLike(node.arguments[0]) && textAttributes.has(node.arguments[0].text)) inspect(node.arguments[1]);
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  for (const [path, css] of Object.entries(files).filter(([path]) => path.endsWith('.css'))) {
    for (const match of css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/(?:^|[;{])\s*content\s*:\s*([^;}]+)/g)) {
      for (const literal of match[1].matchAll(/['"]([^'"]*)['"]/g)) {
        if (hasWords(literal[1]) && !exceptions[path]?.[literal[1]]) failures.add(`${path}: CSS content: ${literal[1]}`);
      }
    }
  }
  for (const [path, markup] of Object.entries(files).filter(([path]) => path.endsWith('.html'))) {
    const html = markup.replace(/<!--[\s\S]*?-->/g, '');
    for (const match of html.matchAll(/>([^<]+)</g)) {
      if (hasWords(match[1])) failures.add(`${path}: HTML text: ${match[1].trim()}`);
    }
    for (const match of html.matchAll(/\b(?:title|alt|placeholder|aria-label|aria-description|aria-valuetext)\s*=\s*["']([^"']*)["']/g)) {
      if (hasWords(match[1])) failures.add(`${path}: HTML attribute: ${match[1]}`);
    }
  }
  return [...failures].sort();
}

describe('UI localization coverage contract', () => {
  it('rejects new visible and accessible literals, including English, local constants and fallback branches', () => {
    const source = `const notice = 'Saved'; function title() { return 'Plain heading'; }
      const labels = { ready: 'Ready' }; const actions = [{ label: 'Remove' }];
      export const ui = <><h1>{title()}</h1><p>{notice}</p><button title="Save" aria-label={'Confirm'}>保存</button>
      <input placeholder={ready ? 'Search' : t('读取中')}/><span>{name || 'Unnamed'}</span><p>{\`Page \${count}\`}</p>
      <p>{labels[status]}</p>{actions.map(action => <button>{action.label}</button>)}</>;
      document.title = 'Library'; input.setCustomValidity('Required');`;
    const failures = auditUi({ './probe.tsx': source, './probe.js': 'node.textContent = "Runtime text"; node.setAttribute("aria-label", "Runtime label");',
      './probe.css': 'p::before { content: "Warning"; }', './index.html': '<title>Startup title</title><noscript>Enable scripts</noscript>' }, {});
    for (const text of ['Saved', 'Plain heading', 'Save', 'Confirm', '保存', 'Search', 'Unnamed', 'Page', 'Library', 'Required', 'Warning', 'Ready', 'Remove', 'Startup title', 'Enable scripts', 'Runtime text', 'Runtime label']) {
      expect(failures.some(failure => failure.endsWith(`: ${text}`)), text).toBe(true);
    }
  });
  it('preserves data and technical identities while requiring translation at the presentation boundary', () => {
    expect(auditUi({ './probe.tsx': `const label = t('保存'); export const ui = <><button title={label}>{label}</button>
      <p>{document.title}</p><input value={draft.text} data-state="pending"/><a href="/settings">{t('设置')}</a>
      <code>PDF</code><span>{ready && t('已完成')}</span></>;`, './probe.css': 'p::before { content: attr(data-label); }' },
    { './probe.tsx': { PDF: 'File format identity.' } })).toEqual([]);
  });
  it('has no unlocalized authored text in application UI, accessibility attributes or CSS content', () => {
    const files = import.meta.glob(['./**/*.ts', './**/*.tsx', './**/*.css', '../index.html', '../../../packages/templates/reader-v15.js', '!./**/*.test.ts', '!./locales/**'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
    expect(Object.keys(files)).toContain('../../../packages/templates/reader-v15.js');
    expect(auditUi(files)).toEqual([]);
  });
  it('has translations for source-key maps as well as direct calls', () => {
    const files = import.meta.glob(['./**/*.ts', './**/*.tsx', '!./**/*.test.ts', '!./locales/**', '!./i18n.ts', '!./languages.ts'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
    const missing: string[] = [];
    for (const [path, source] of Object.entries(files)) {
      const ast = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
      function visit(node: ts.Node) {
        if (ts.isStringLiteralLike(node) && /[\u3400-\u9fff]/.test(node.text) && !messages[node.text] && !dataLiteralExceptions[path]?.[node.text]) missing.push(`${path}: ${node.text}`);
        ts.forEachChild(node, visit);
      }
      visit(ast);
    }
    expect(missing).toEqual([]);
  });
});
