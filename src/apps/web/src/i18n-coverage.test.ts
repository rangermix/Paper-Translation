import { describe, expect, it } from 'vitest';
import ts from 'typescript';
import { messages } from './i18n';

// Exceptions are exact values in named files, never entire components or languages.
// They are identities/data formats, not application instructions or status text.
const literalExceptions: Record<string, Record<string, string>> = {
  './features/history.tsx': { '· reader-v16': 'Immutable template identifier.' },
  './domain.ts': { USD: 'Currency code used by the money formatter.' },
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
const textAttributes = new Set(['title', 'placeholder', 'alt', 'aria-label', 'aria-description', 'aria-roledescription', 'aria-valuetext', 'label', 'emptyLabel', 'buttonLabel', 'description', 'data-label']);
const hasWords = (value: string) => /\p{L}/u.test(value);
const nativeNameDeclarations: Record<string, Record<string, string>> = {
  './languages.ts': { nativeNames: 'Language autonyms remain in their own language; adjacent localized names use Intl.DisplayNames.' },
  './i18n.ts': { uiLocales: 'Language selector choices remain recognizable autonyms in every UI language.' },
};
const dataLiteralExceptions: Record<string, Record<string, string>> = {
  './domain.ts': { '保护内容': 'Legacy malformed-inline sentinel; changing its text changes content/selection offsets.' },
  './features/inline-editing.ts': { '保护内容': 'Same stable malformed-inline sentinel as domain.inlineText; accessibility labels are localized separately.' },
};

/** Inspect text-producing expressions, not event handlers, routing IDs or user data. */
function auditUi(files: Record<string, string>, exceptions = literalExceptions) {
  const normalizePath = (path: string) => path.split('/').reduce<string[]>((parts, part) => {
    if (part === '..' && parts.length && parts.at(-1) !== '..') parts.pop();
    else if (part !== '.' && part !== '') parts.push(part);
    return parts;
  }, []).join('/');
  const sources = new Map(Object.entries(files).filter(([path]) => /\.[tj]sx?$/.test(path)).map(([path, source]) =>
    [path.replace(/^\.\//, ''), ts.createSourceFile(path.replace(/^\.\//, ''), source, ts.ScriptTarget.Latest, true, path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)]));
  const host: ts.CompilerHost = {
    getSourceFile: path => sources.get(path), getDefaultLibFileName: () => '', writeFile: () => {},
    getCurrentDirectory: () => '', getDirectories: () => [], fileExists: path => sources.has(path),
    readFile: path => files[`./${path}`], getCanonicalFileName: path => path, useCaseSensitiveFileNames: () => true, getNewLine: () => '\n',
    resolveModuleNames: (names, containingFile) => names.map(name => {
      if (!name.startsWith('.')) return undefined;
      const base = normalizePath(`${containingFile.slice(0, containingFile.lastIndexOf('/') + 1)}${name}`);
      const resolvedFileName = [base, `${base}.ts`, `${base}.tsx`, `${base}.js`, `${base}/index.ts`, `${base}/index.tsx`].find(path => sources.has(path));
      return resolvedFileName ? { resolvedFileName, isExternalLibraryImport: false } : undefined;
    }),
  };
  const program = ts.createProgram([...sources.keys()], { noLib: true, allowJs: true, jsx: ts.JsxEmit.Preserve }, host);
  const checker = program.getTypeChecker();
  const declarations = (node: ts.Node) => {
    let symbol = checker.getSymbolAtLocation(node);
    if (symbol && symbol.flags & ts.SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol);
    return symbol?.declarations ?? [];
  };
  const failures = new Set<string>();
  for (const source of sources.values()) {
    function report(node: ts.Node, value: string) {
      const origin = node.getSourceFile();
      const originPath = `./${origin.fileName}`;
      const text = value.trim();
      if (!hasWords(text) || exceptions[originPath]?.[text]) return;
      let ancestor: ts.Node | undefined = node;
      while (ancestor && !ts.isVariableDeclaration(ancestor)) ancestor = ancestor.parent;
      if (ancestor && ts.isIdentifier(ancestor.name) && nativeNameDeclarations[originPath]?.[ancestor.name.text]) return;
      const { line } = origin.getLineAndCharacterOfPosition(node.getStart(origin));
      failures.add(`${originPath}:${line + 1}: ${text}`);
    }
    function members(node: ts.Node | undefined, key: string | undefined, seen: Set<ts.Node>): ts.Node[] {
      if (!node || seen.has(node)) return [];
      seen = new Set(seen).add(node);
      if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node)) return members(node.expression, key, seen);
      if (ts.isArrayLiteralExpression(node)) return node.elements.flatMap(element => members(element, key, seen));
      if (ts.isObjectLiteralExpression(node)) return node.properties.flatMap(property => ts.isPropertyAssignment(property) &&
        (key === undefined || property.name.getText().replace(/^['"]|['"]$/g, '') === key) ? [property.initializer] : []);
      if (ts.isIdentifier(node)) return declarations(node).flatMap(declaration => {
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
    function arrayItems(node: ts.Node | undefined, seen = new Set<ts.Node>()): ts.Node[] {
      if (!node || seen.has(node)) return [];
      seen = new Set(seen).add(node);
      if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node)) return arrayItems(node.expression, seen);
      if (ts.isArrayLiteralExpression(node)) return [...node.elements];
      if (ts.isIdentifier(node)) return declarations(node).flatMap(declaration => ts.isVariableDeclaration(declaration) ? arrayItems(declaration.initializer, seen) : []);
      return [];
    }
    function bindingValues(binding: ts.BindingElement): ts.Node[] {
      const pattern = binding.parent, owner = pattern.parent;
      const key = ts.isObjectBindingPattern(pattern) ? (binding.propertyName ?? binding.name).getText().replace(/^['"]|['"]$/g, '') : undefined;
      if (ts.isVariableDeclaration(owner)) {
        return key !== undefined ? members(owner.initializer, key, new Set()) : arrayItems(owner.initializer).filter((_, index) => index === pattern.elements.indexOf(binding));
      }
      if (!ts.isParameter(owner) || !ts.isArrowFunction(owner.parent)) return [];
      const call = owner.parent.parent;
      if (!ts.isCallExpression(call) || !ts.isPropertyAccessExpression(call.expression) || call.expression.name.text !== 'map') return [];
      const collection = call.expression.expression;
      if (key !== undefined) return members(collection, key, new Set());
      const index = pattern.elements.indexOf(binding);
      if (index === 1 && ts.isCallExpression(collection) && ts.isPropertyAccessExpression(collection.expression) &&
          collection.expression.expression.getText() === 'Object' && collection.expression.name.text === 'entries') {
        return members(collection.arguments[0], undefined, new Set());
      }
      return arrayItems(collection).flatMap(item => arrayItems(item).filter((_, position) => position === index));
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
        declarations(node).forEach(declaration => {
          if (ts.isVariableDeclaration(declaration)) inspect(declaration.initializer, seen);
          if (ts.isParameter(declaration)) inspect(declaration.initializer, seen);
          if (ts.isBindingElement(declaration)) {
            inspect(declaration.initializer, seen);
            bindingValues(declaration).forEach(value => inspect(value, seen));
          }
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
        declarations(node.expression).forEach(declaration => {
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
  it('follows imported labels, option maps and helper functions without exempting a whole module', () => {
    const files = {
      './copy.ts': `export const label = 'Shared label'; export const options = [{ label: 'Shared option' }];
        export const titles = { empty: 'Shared empty state' }; export const tuples = [['id', 'Shared tuple']];
        export const descriptions = { name: 'Shared description' }; export function heading() { return 'Shared heading'; }`,
      './ui.tsx': `import {label as alias, options, titles, tuples, descriptions, heading} from './copy'; export const ui = <>
        <h1>{heading()}</h1><p>{titles[state]}</p><button aria-label={alias}>{alias}</button>
        {options.map(option => <option>{option.label}</option>)}{options.map(({label}) => <option>{label}</option>)}
        {tuples.map(([id, label]) => <Item key={id} emptyLabel={label}/>)}
        {Object.entries(descriptions).map(([key, text]) => <p key={key}>{text}</p>)}</>;`,
    };
    const failures = auditUi(files, {});
    for (const value of ['Shared label', 'Shared option', 'Shared empty state', 'Shared heading', 'Shared tuple', 'Shared description']) {
      expect(failures.some(failure => failure.startsWith('./copy.ts:') && failure.endsWith(`: ${value}`)), value).toBe(true);
    }
    const fixed = Object.fromEntries(Object.entries(files).map(([path, source]) => [path,
      path === './copy.ts' ? source.replace(/'Shared ([^']+)'/g, "t('Shared $1')") : source]));
    expect(auditUi(fixed, {})).toEqual([]);
  });
  it('has no unlocalized authored text in application UI, accessibility attributes or CSS content', () => {
    const files = import.meta.glob(['./**/*.ts', './**/*.tsx', './**/*.css', '../index.html', '../../../packages/templates/reader-v16.js', '!./**/*.test.ts', '!./locales/**'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
    // Vite normalizes excess parent segments at the filesystem root in Docker.
    // Both the checkout and /web build must still include the actual reader file.
    expect(Object.keys(files).some(path => path.endsWith('/packages/templates/reader-v16.js'))).toBe(true);
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
