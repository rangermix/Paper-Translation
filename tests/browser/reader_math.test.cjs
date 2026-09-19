const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('unsupported OCR math keeps its visible source text after KaTeX clears the node', () => {
  const root = path.resolve(__dirname, '../..');
  const katex = require(path.join(root, 'res/vendor/katex-0.18.7/katex.min.js'));
  const text = '$\\invalidCommand{x}$';
  const classes = new Set();
  const node = { textContent: text, dataset: { tex: '\\invalidCommand{x}', display: 'false' },
    classList: { add: value => classes.add(value) }, setAttribute() {} };
  const callbacks = [];
  const document = { addEventListener: (_, callback) => callbacks.push(callback),
    querySelectorAll: () => [node] };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'src/packages/templates/reader-v4.js'), 'utf8'),
    { document, window: { katex } });
  callbacks[0]();
  assert.equal(node.textContent, text);
  assert.ok(classes.has('math-error'));
  assert.equal(node.dataset.mathRendered, undefined);
});
